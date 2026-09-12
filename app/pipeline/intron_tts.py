from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect


class IntronTTSProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntronTTSConfig:
    endpoint: str
    api_key: str
    voice_accent: str
    voice_gender: str
    language: str = "en"
    output_audio_format: str = "wav"
    sample_rate: int = 48000
    text_chunk_chars: int = 100
    poll_interval_seconds: float = 0.05
    request_timeout_seconds: float = 10.0


class IntronTTSStream:
    """Async client for Intron's documented TTS streaming protocol."""

    _ERRORS = {
        "ERROR",
        "INPUT_ERROR",
        "AUTHENTICATION_ERROR",
        "RESOURCE_EXHAUSTED",
        "QUOTA_EXCEEDED",
        "SESSION_TIME_LIMIT_EXCEEDED",
        "INSUFFICIENT_TEXT_ACTIVITY",
        "CHUNK_ID_MISMATCH_WITH_TOTAL",
        "CHUNCK_SIZE_TOO_SMALL",
        "CHUNK_SIZE_TOO_SMALL",
        "CHUNK_SIZE_TOO_LARGE",
    }

    def __init__(self, config: IntronTTSConfig) -> None:
        self._config = config
        self._ws: ClientConnection | None = None
        self._next_chunk_id = 1

    def _url(self) -> str:
        if not self._config.voice_accent or not self._config.voice_gender:
            raise IntronTTSProtocolError("INTRON_TTS_VOICE_ACCENT and INTRON_TTS_VOICE_GENDER are required")
        params = {
            "voice_accent": self._config.voice_accent,
            "voice_gender": self._config.voice_gender,
            "voice_language": self._config.language,
            "output_audio_format": self._config.output_audio_format,
        }
        return f"{self._config.endpoint}?{urlencode(params)}"

    async def connect(self) -> dict[str, Any]:
        if not self._config.api_key:
            raise IntronTTSProtocolError("INTRON_API_KEY is not configured")
        self._next_chunk_id = 1
        self._ws = await connect(
            self._url(),
            additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
            open_timeout=self._config.request_timeout_seconds,
        )
        event = await self._receive_json()
        if event.get("message_type") != "SESSION_CREATED":
            raise IntronTTSProtocolError(f"Expected SESSION_CREATED, got {event.get('message_type')}")
        return event

    async def send_text(self, text: str, ack_id: int | None = None) -> int:
        if self._ws is None:
            raise RuntimeError("TTS stream is not connected")
        value = text.strip()
        if not 10 <= len(value) <= 100:
            raise ValueError("Intron TTS text chunk must contain 10-100 characters")
        current_id = ack_id if ack_id is not None else self._next_chunk_id
        if current_id != self._next_chunk_id:
            raise ValueError("TTS chunk IDs must be sequential")
        self._next_chunk_id += 1
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "INPUT_TEXT_CHUNK",
                    "text": value,
                    "ack_id": current_id,
                }
            )
        )
        return current_id

    async def fetch_audio(self, chunk_id: int) -> bytes:
        if self._ws is None:
            raise RuntimeError("TTS stream is not connected")
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "FETCH_AUDIO_CHUNK",
                    "chunk_id": chunk_id,
                }
            )
        )
        deadline = asyncio.get_running_loop().time() + self._config.request_timeout_seconds
        while True:
            event = await self._receive_json()
            message_type = event.get("message_type")
            if message_type in self._ERRORS:
                raise IntronTTSProtocolError(f"Intron TTS error: {message_type}")
            if message_type != "FETCH_AUDIO_CHUNK":
                continue
            returned_id = event.get("chunk_id")
            if returned_id is not None and int(returned_id) != chunk_id:
                raise IntronTTSProtocolError("Intron returned audio for an unexpected chunk")
            status = str(event.get("processing_status") or event.get("processing_staus") or "").upper()
            if status == "READY":
                audio = _audio_from_event(event)
                if not audio:
                    raise IntronTTSProtocolError("Intron marked audio READY but returned no audio")
                return audio
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Timed out waiting for Intron TTS audio")
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def commit(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("TTS stream is not connected")
        await self._ws.send(json.dumps({"message_type": "COMMIT"}))
        while True:
            event = await self._receive_json()
            message_type = event.get("message_type")
            if message_type == "COMMITTED_AUDIO":
                return event
            if message_type in self._ERRORS:
                raise IntronTTSProtocolError(f"Intron TTS terminal error: {message_type}")

    async def iter_audio(self, text: str) -> AsyncIterator[bytes]:
        await self.connect()
        try:
            for chunk in _chunk_text(text, self._config.text_chunk_chars):
                chunk_id = await self.send_text(chunk)
                yield await self.fetch_audio(chunk_id)
            await self.commit()
        finally:
            await self.close()

    async def iter_audio_stream(self, text_chunks: AsyncIterator[str]) -> AsyncIterator[bytes]:
        """Stream text chunks from LLM into a single Intron TTS session.

        Buffers LLM text chunks into Intron-compliant 10-100 char chunks
        and yields audio as it arrives. Keeps one WebSocket session open
        for the entire response.
        """
        await self.connect()
        buffer = ""
        try:
            async for chunk in text_chunks:
                buffer += chunk
                while len(buffer) >= self._config.text_chunk_chars:
                    # Take a chunk that fits Intron's 10-100 char limit
                    send_text = buffer[: self._config.text_chunk_chars]
                    buffer = buffer[len(send_text):]
                    chunk_id = await self.send_text(send_text)
                    yield await self.fetch_audio(chunk_id)
            # Flush remaining buffer
            if buffer.strip():
                # Intron requires 10-100 chars per chunk
                if len(buffer) < 10:
                    # Pad with trailing characters or append to previous chunk
                    # For now, send as-is - Intron may accept short final text
                    chunk_id = await self.send_text(buffer + " ...")
                else:
                    chunk_id = await self.send_text(buffer)
                yield await self.fetch_audio(chunk_id)
            await self.commit()
        finally:
            await self.close()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _receive_json(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("TTS stream is not connected")
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raise IntronTTSProtocolError("Expected JSON text response from Intron TTS")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise IntronTTSProtocolError("Intron TTS response was not an object")
        return data


def _chunk_text(text: str, max_chars: int) -> list[str]:
    max_chars = min(max(max_chars, 10), 100)
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        if len(current) < 10 and chunks and len(chunks[-1]) + 1 + len(current) <= max_chars:
            chunks[-1] = f"{chunks[-1]} {current}"
        elif len(current) < 10:
            current = f"{current} ...".strip()
        chunks.append(current)
    return chunks


def _audio_from_event(event: dict[str, Any]) -> bytes | None:
    value = event.get("audio_base_64") or event.get("audio") or event.get("audio_base64")
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise IntronTTSProtocolError("Invalid base64 audio in Intron TTS response") from exc
    return None
