from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import Settings, get_settings
from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.field_schema import ExtractedFields, RequiredFieldPolicy
from app.dialogue.llm_provider import NvidiaClient, NvidiaExtractionProvider, NvidiaResponseGenerator
from app.dialogue.response_generation import SafeFallbackResponseGenerator
from app.dialogue.translation import NllbTranslationProvider
from app.integrations.conversation_repository import ConversationRepository
from app.integrations.supabase_client import create_supabase
from app.pipeline.intron_stream import IntronConfig, IntronSTTStream
from app.pipeline.intron_tts import IntronTTSStream, IntronTTSConfig
from app.pipeline.pipecat_frame_pipeline import build_pipecat_pipeline
from app.pipeline.pipecat_pipeline import ConversationPipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["conversation"])


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_pipeline(settings: Settings) -> ConversationPipeline:
    required_policy = RequiredFieldPolicy(fields=_csv(settings.required_triage_fields))
    danger_matcher = DangerMatcher(_csv(settings.danger_sign_phrases))
    if settings.nvidia_api_key:
        extraction_client = NvidiaClient(settings, model=settings.nvidia_extraction_model)
        response_client = NvidiaClient(settings, model=settings.nvidia_response_model)
        extractor: Any = NvidiaExtractionProvider(extraction_client, required_policy.fields)
        responder: Any = NvidiaResponseGenerator(response_client)
    else:
        extractor = _UnavailableExtractionProvider()
        responder = SafeFallbackResponseGenerator()
    return ConversationPipeline(
        extraction_provider=extractor,
        translation_provider=NllbTranslationProvider(settings),
        danger_matcher=danger_matcher,
        response_generator=responder,
        required_fields_checker=required_policy.is_complete,
    )


class _UnavailableExtractionProvider:
    async def extract(self, transcript: str) -> ExtractedFields:
        raise RuntimeError("NVIDIA_API_KEY is not configured")


def build_stt(settings: Settings) -> IntronSTTStream:
    return IntronSTTStream(
        IntronConfig(
            endpoint=settings.intron_stt_endpoint,
            api_key=settings.intron_stt_api_key,
            sample_rate=settings.intron_stt_sample_rate,
            bit_rate=settings.intron_stt_bit_rate,
            num_channels=settings.intron_stt_channels,
            language=settings.intron_stt_language,
        )
    )


def build_tts(settings: Settings) -> IntronTTSStream:
    return IntronTTSStream(
        IntronTTSConfig(
            endpoint=settings.intron_tts_endpoint,
            api_key=settings.intron_tts_api_key,
            voice_accent=settings.intron_tts_voice_accent or settings.intron_tts_voice,
            voice_gender=settings.intron_tts_voice_gender,
            language=settings.intron_tts_language,
            output_audio_format=settings.intron_tts_output_audio_format,
            sample_rate=settings.intron_tts_sample_rate,
            text_chunk_chars=settings.intron_tts_text_chunk_chars,
        )
    )


@router.websocket("/conversations/ws")
async def conversation_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    repository: ConversationRepository | None = None
    conversation_id: UUID | None = None
    runner_task: asyncio.Task[Any] | None = None
    terminal_status = "completed"
    try:
        if not settings.intron_stt_api_key or not settings.intron_tts_api_key:
            await _fail(websocket, "VOICE_PROVIDER_NOT_CONFIGURED")
            return

        supabase = await create_supabase(settings)
        repository = ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)
        patient_id = await _resolve_patient(websocket, repository, settings)
        if patient_id is None:
            await _fail(websocket, "PATIENT_AUTH_REQUIRED")
            return
        conversation_id = await repository.create_conversation(patient_id=patient_id, channel="web")
        previous_turn, previous_fields = await repository.load_context(conversation_id)

        stt = build_stt(settings)
        tts = build_tts(settings)
        logic = build_pipeline(settings)
        task, commit_frame_type = build_pipecat_pipeline(
            websocket=websocket,
            settings=settings,
            conversation_id=conversation_id,
            repository=repository,
            pipeline_logic=logic,
            stt=stt,
            tts=tts,
            initial_turn_number=previous_turn,
            initial_fields=previous_fields,
        )
        from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame, TTSSpeakFrame  # type: ignore[import-not-found]
        from pipecat.workers.runner import WorkerRunner  # type: ignore[import-not-found]

        runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        await runner.add_workers(task)
        runner_task = asyncio.create_task(runner.run())
        # PipelineWorker injects StartFrame itself. The greeting is the first data
        # frame queued, so the client receives speech without an LLM round-trip.
        await task.queue_frame(TTSSpeakFrame("Hello. I am your community health assistant. How can I help you today?"))

        receive_task: asyncio.Task[Any] | None = None
        while True:
            receive_task = asyncio.create_task(websocket.receive_json())
            done, _ = await asyncio.wait(
                {receive_task, runner_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if runner_task in done:
                error = runner_task.exception()
                if error:
                    raise RuntimeError("Pipecat worker stopped unexpectedly") from error
                raise RuntimeError("Pipecat worker stopped unexpectedly")
            message = receive_task.result()
            receive_task = None
            message_type = message.get("message_type")
            if message_type == "INPUT_AUDIO_CHUNK":
                audio = _decode_audio(message.get("audio_base_64"))
                if audio is None:
                    await _input_error(websocket, "INVALID_AUDIO_CHUNK")
                    continue
                if not 1024 <= len(audio) <= 32768:
                    await _input_error(websocket, "CHUNK_SIZE_TOO_SMALL" if len(audio) < 1024 else "CHUNK_SIZE_TOO_LARGE")
                    continue
                await task.queue_frame(
                    InputAudioRawFrame(
                        audio=audio,
                        sample_rate=settings.intron_stt_sample_rate,
                        num_channels=settings.intron_stt_channels,
                    )
                )
            elif message_type == "COMMIT":
                await task.queue_frame(commit_frame_type())
            elif message_type in {"INTERRUPT", "START_INTERRUPTION"}:
                await task.queue_frame(InterruptionFrame())
            elif message_type == "PING":
                await websocket.send_json({"message_type": "PONG"})
            else:
                await _input_error(websocket, "UNKNOWN_MESSAGE_TYPE")
    except WebSocketDisconnect:
        logger.info("conversation websocket disconnected")
        terminal_status = "disconnected"
    except Exception as exc:
        terminal_status = "escalated"
        logger.exception("conversation websocket failed", extra={"error_type": type(exc).__name__})
        with contextlib.suppress(Exception):
            await _fail(websocket, "PIPELINE_FAILURE_ESCALATE")
    finally:
        if receive_task and not receive_task.done():
            receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await receive_task
        if conversation_id and repository:
            with contextlib.suppress(Exception):
                await repository.finish_conversation(conversation_id, status=terminal_status)
        if runner_task:
            runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner_task


async def _resolve_patient(
    websocket: WebSocket,
    repository: ConversationRepository,
    settings: Settings,
) -> UUID | None:
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            try:
                row = await repository.patient_for_access_token(token)
                if row:
                    return UUID(str(row["id"]))
            except Exception as exc:
                logger.warning("websocket auth verification failed", extra={"error_type": type(exc).__name__})
    if settings.environment == "development" and settings.allow_dev_unauthenticated:
        raw_patient_id = websocket.query_params.get("patient_id")
        if raw_patient_id:
            try:
                patient = await repository.patient_by_id(UUID(raw_patient_id))
                if patient:
                    return UUID(str(patient["id"]))
            except ValueError:
                return None
    return None


def _decode_audio(value: Any) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


async def _input_error(websocket: WebSocket, code: str) -> None:
    await websocket.send_json({"message_type": "INPUT_ERROR", "code": code})


async def _fail(websocket: WebSocket, code: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.send_json({"message_type": "ERROR", "code": code, "escalate": True})
    with contextlib.suppress(Exception):
        await websocket.close(code=1011)
