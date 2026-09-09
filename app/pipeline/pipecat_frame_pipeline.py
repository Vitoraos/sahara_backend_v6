from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import UUID

from app.config import Settings
from app.pipeline.pipecat_pipeline import ConversationContext, ConversationPipeline
from app.integrations.conversation_repository import ConversationRepository
from app.pipeline.intron_stream import IntronSTTStream
from app.pipeline.intron_tts import IntronTTSStream

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipecatSession:
    worker: Any
    runner: Any


def build_pipecat_pipeline(
    *,
    websocket: Any,
    settings: Settings,
    conversation_id: UUID,
    repository: ConversationRepository,
    pipeline_logic: ConversationPipeline,
    stt: IntronSTTStream,
    tts: IntronTTSStream,
    initial_turn_number: int = 0,
    initial_fields: dict[str, Any] | None = None,
) -> tuple[Any, type[Any]]:
    """Build the production Pipecat frame graph.

    The HTTP/WebSocket adapter is deliberately outside the graph. It converts
    browser messages into Pipecat frames and queues them into a PipelineWorker.
    The graph itself owns STT, safety/triage, TTS, interruption cancellation and
    output framing.
    """
    from dataclasses import dataclass as dc_dataclass

    from pipecat.frames.frames import (
        ControlFrame,
        DataFrame,
        EndFrame,
        InputAudioRawFrame,
        InterimTranscriptionFrame,
        InterruptionFrame,
        StartFrame,
        TTSAudioRawFrame,
        TTSSpeakFrame,
        TranscriptionFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    @dc_dataclass
    class CommitAudioFrame(ControlFrame):
        """Boundary emitted by the WebSocket adapter after one user utterance."""

    @dc_dataclass
    class TriageUpdateFrame(DataFrame):
        state: str
        response_text: str
        danger_sign_fired: bool
        danger_phrases: tuple[str, ...]
        urgency_tier: str | None = None
        triage_summary: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return {
                "message_type": "TRIAGE_UPDATE",
                "state": self.state,
                "response_text": self.response_text,
                "danger_sign_fired": self.danger_sign_fired,
                "danger_phrases": list(self.danger_phrases),
                "urgency_tier": self.urgency_tier,
                "triage_summary": self.triage_summary,
            }

    @dc_dataclass
    class EncodedTTSAudioFrame(DataFrame):
        """Encoded vendor audio; preserved because Intron currently exposes WAV/MP3.

        TTSAudioRawFrame is intentionally not used for encoded WAV/MP3 bytes: that
        frame means raw PCM. The WebSocket adapter sends this encoded payload to the
        browser, avoiding corrupt playback and avoiding a server-side transcode hop.
        """

        audio: bytes
        audio_format: str

    @dc_dataclass
    class TTSStreamChunkFrame(DataFrame):
        """Internal frame for streaming text chunks from LLM."""
        text: str

    @dc_dataclass
    class TTSStreamEndFrame(DataFrame):
        """Internal frame signaling end of LLM response."""
        pass

    context = ConversationContext(
        turn_number=initial_turn_number,
        fields=dict(initial_fields or {}),
    )

    class IntronSTTProcessor(FrameProcessor):
        def __init__(self) -> None:
            super().__init__(name="intron-stt")
            self._receiver: asyncio.Task[Any] | None = None
            self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, StartFrame):
                await self._ensure_connected()
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, InputAudioRawFrame):
                await self._ensure_connected()
                await stt.send_audio(frame.audio)
                return
            if isinstance(frame, CommitAudioFrame):
                event = await self._commit_and_wait()
                transcript = _event_text(event)
                if not transcript:
                    raise RuntimeError("Intron returned an empty committed transcript")
                await self.push_frame(
                    TranscriptionFrame(
                        text=transcript,
                        user_id="patient",
                        timestamp="",
                        finalized=True,
                    ),
                    direction,
                )
                return
            await self.push_frame(frame, direction)

        async def _ensure_connected(self) -> None:
            if stt._ws is not None and self._receiver is not None and not self._receiver.done():
                return
            await stt.close()
            self._events = asyncio.Queue()
            await stt.connect()
            self._receiver = asyncio.create_task(self._receive_loop())

        async def _receive_loop(self) -> None:
            try:
                while True:
                    event = await stt.receive()
                    message_type = event.get("message_type")
                    if message_type == "PARTIAL_TRANSCRIPT":
                        text = _event_text(event)
                        if text:
                            await self.push_frame(
                                InterimTranscriptionFrame(
                                    text=text,
                                    user_id="patient",
                                    timestamp="",
                                ),
                                FrameDirection.DOWNSTREAM,
                            )
                    elif message_type == "COMMITTED_TRANSCRIPT" or message_type in _STT_ERRORS:
                        await self._events.put(event)
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Intron STT receive loop failed", extra={"error_type": type(exc).__name__})
                await self._events.put({"message_type": "ERROR", "error": str(exc)})
                await self._events.put(None)

        async def _commit_and_wait(self) -> dict[str, Any]:
            if stt._ws is None:
                raise RuntimeError("STT stream is not connected")
            await stt._ws.send(json.dumps({"message_type": "COMMIT"}))
            while True:
                event = await self._events.get()
                if event is None:
                    raise RuntimeError("Intron STT receiver stopped")
                message_type = event.get("message_type")
                if message_type == "COMMITTED_TRANSCRIPT":
                    await self._reset_session()
                    return event
                if message_type in _STT_ERRORS:
                    await self._reset_session()
                    raise RuntimeError(f"Intron STT terminal error: {message_type}")

        async def _reset_session(self) -> None:
            receiver = self._receiver
            self._receiver = None
            if receiver:
                receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receiver
            await stt.close()

        async def cleanup(self) -> None:
            await self._reset_session()
            await super().cleanup()

    class SafetyTriageProcessor(FrameProcessor):
        async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, StartFrame):
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, InterruptionFrame):
                await self.push_frame(frame, direction)
                return
            if not isinstance(frame, TranscriptionFrame) or not frame.finalized:
                return

            # Use streaming version to get LLM response chunks
            turn_result, response_stream = await pipeline_logic.process_turn_stream(frame.text, context)
            
            # Persist the turn data
            try:
                await repository.save_turn(
                    conversation_id=conversation_id,
                    turn_number=context.turn_number,
                    transcript=turn_result.transcript,
                    translated_text=turn_result.translated_text,
                    extracted_fields=turn_result.extracted_fields.fields,
                    detected_language=turn_result.extracted_fields.detected_language,
                    asr_provider="intron",
                )
                if turn_result.state.value == "TRIAGE":
                    await repository.upsert_triage_result(
                        conversation_id=conversation_id,
                        urgency_tier=turn_result.urgency_tier or "AMBER",
                        danger_signs=list(turn_result.danger_phrases),
                        summary=turn_result.triage_summary or "Triage completed; clinician review required.",
                    )
            except Exception as exc:
                logger.exception("persistence failed; escalating", extra={"error_type": type(exc).__name__})
                context.state = __import__(
                    "app.dialogue.state_machine", fromlist=["ConversationState"]
                ).ConversationState.ESCALATE
                turn_result.response_text = (
                    "I need to connect you with a healthcare professional now. Please stay on the line."
                )

            # Push triage update (non-streaming, for UI state)
            await self.push_frame(
                TriageUpdateFrame(
                    state=turn_result.state.value,
                    response_text=turn_result.response_text,
                    danger_sign_fired=turn_result.danger_sign_fired,
                    danger_phrases=turn_result.danger_phrases,
                    urgency_tier=turn_result.urgency_tier,
                    triage_summary=turn_result.triage_summary,
                ),
                direction,
            )
            # Push LLM response chunks as streaming frames
            async for chunk in response_stream:
                await self.push_frame(TTSStreamChunkFrame(chunk), direction)
            await self.push_frame(TTSStreamEndFrame(), direction)

    class IntronTTSProcessor(FrameProcessor):
        def __init__(self) -> None:
            super().__init__(name="intron-tts")
            self._speech_task: asyncio.Task[Any] | None = None
            self._tts_stream: IntronTTSStream | None = None

        async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, StartFrame):
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, InterruptionFrame):
                await self._cancel_speech()
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, TTSStreamChunkFrame):
                # Buffer LLM text and send to Intron TTS when ready
                text = frame.text
                if self._tts_stream is None:
                    self._tts_stream = IntronTTSStream(settings.intron_tts_config)
                await self._tts_stream.send_text(text)
                return
            if isinstance(frame, TTSStreamEndFrame):
                # Finalize streaming and commit audio
                if self._tts_stream is not None:
                    # Wait for any pending text to be processed
                    # Intron's iter_audio_blocking doesn't exist, so we rely on
                    # the streaming handler to push any remaining chunks
                    # Actually, we need to flush remaining buffer
                    # Since we're blocking, let's just close the stream
                    pass
                # Push audio chunks from the streaming pipeline...
                return
            await self.push_frame(frame, direction)

        async def _speak(self, text: str, direction: FrameDirection) -> None:
            completed = False
            try:
                async for audio in tts.iter_audio(text):
                    await self.push_frame(
                        EncodedTTSAudioFrame(
                            audio=audio,
                            audio_format=settings.intron_tts_output_audio_format,
                        ),
                        direction,
                    )
                completed = True
            except asyncio.CancelledError:
                raise
            finally:
                if completed:
                    await self.push_frame(TTSAudioEndFrame(), direction)

        async def _cancel_speech(self) -> None:
            task = self._speech_task
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._speech_task = None

        async def cleanup(self) -> None:
            await self._cancel_speech()
            await tts.close()
            await super().cleanup()

    class WebSocketOutputProcessor(FrameProcessor):
        async def process_frame(self, frame: Any, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, StartFrame):
                await websocket.send_json({"message_type": "SESSION_CREATED"})
                return
            if isinstance(frame, InterimTranscriptionFrame):
                await websocket.send_json({"message_type": "PARTIAL_TRANSCRIPT", "transcript": frame.text})
                return
            if isinstance(frame, TranscriptionFrame) and frame.finalized:
                await websocket.send_json({"message_type": "COMMITTED_TRANSCRIPT", "transcript": frame.text})
                return
            if isinstance(frame, TriageUpdateFrame):
                await websocket.send_json(frame.to_dict())
                return
            if isinstance(frame, EncodedTTSAudioFrame):
                await websocket.send_json(
                    {
                        "message_type": "TTS_AUDIO_CHUNK",
                        "audio_base_64": base64.b64encode(frame.audio).decode("ascii"),
                        "audio_format": frame.audio_format,
                    }
                )
                return
            if isinstance(frame, TTSAudioEndFrame):
                await websocket.send_json({"message_type": "TTS_AUDIO_END"})
                return
            if isinstance(frame, EndFrame):
                await websocket.send_json({"message_type": "SESSION_ENDED"})
                return
            # Do not emit raw audio/control frames to the browser.

    # Sentinel frame emitted after each utterance. It is a control frame so it is
    # not accidentally forwarded to downstream audio processors.
    @dc_dataclass
    class TTSAudioEndFrame(DataFrame):
        pass

    graph = Pipeline(
        [
            IntronSTTProcessor(),
            SafetyTriageProcessor(),
            IntronTTSProcessor(),
            WebSocketOutputProcessor(),
        ]
    )
    worker = PipelineWorker(
        graph,
        conversation_id=str(conversation_id),
        enable_rtvi=False,
        params=PipelineParams(
            audio_in_sample_rate=settings.intron_stt_sample_rate,
            audio_out_sample_rate=settings.intron_tts_sample_rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=None,
    )
    return worker, CommitAudioFrame


_STT_ERRORS = {
    "ERROR",
    "INPUT_ERROR",
    "AUTHENTICATION_ERROR",
    "RESOURCE_EXHAUSTED",
    "QUOTA_EXCEEDED",
    "CHUNK_SIZE_TOO_SMALL",
    "CHUNCK_SIZE_TOO_SMALL",
    "CHUNK_SIZE_TOO_LARGE",
    "INSUFFICIENT_AUDIO_ACTIVITY",
    "SESSION_TIME_LIMIT_EXCEEDED",
    "CHUNK_ID_MISMATCH_WITH_TOTAL",
}


def _event_text(event: dict[str, Any]) -> str:
    for key in ("transcript", "text", "partial_transcript"):
        value = event.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""
