from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection, connect


class IntronProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntronConfig:
    endpoint: str
    api_key: str
    sample_rate: int = 16000
    bit_rate: int = 16
    num_channels: int = 1
    language: str = "en"


class IntronSTTStream:
    """Thin async client for Intron's documented streaming STT protocol."""

    def __init__(self, config: IntronConfig) -> None:
        self._config = config
        self._ws: ClientConnection | None = None
        self._next_ack_id = 1

    def set_language(self, language: str) -> None:
        """Switches the ASR input language for the next connection.

        Takes effect on reconnect — the STT processor already drops and
        re-opens the Intron stream after every committed utterance.
        """
        self._config = dataclasses.replace(self._config, language=language)

    def _url(self) -> str:
        params = (
            f"sample_rate={self._config.sample_rate}"
            f"&bit_rate={self._config.bit_rate}"
            f"&num_channels={self._config.num_channels}"
            f"&use_language_asr_input={self._config.language}"
        )
        return f"{self._config.endpoint}?{params}"

    async def connect(self) -> dict[str, Any]:
        self._next_ack_id = 1
        self._ws = await connect(
            self._url(),
            additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
            open_timeout=10,
        )
        message = await self._receive_json()
        if message.get("message_type") != "SESSION_CREATED":
            raise IntronProtocolError(f"Expected SESSION_CREATED, got {message.get('message_type')}")
        return message

    async def send_audio(self, pcm16le: bytes, ack_id: int | None = None) -> int:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        if not 1024 <= len(pcm16le) <= 32768:
            raise ValueError("Intron audio chunk must be between 1 KB and 32 KB")
        chunk_id = ack_id if ack_id is not None else self._next_ack_id
        self._next_ack_id = max(self._next_ack_id, chunk_id + 1)
        payload = {
            "message_type": "INPUT_AUDIO_CHUNK",
            "audio_base_64": base64.b64encode(pcm16le).decode("ascii"),
            "ack_id": chunk_id,
        }
        await self._ws.send(json.dumps(payload))
        return chunk_id

    async def receive(self) -> dict[str, Any]:
        return await self._receive_json()

    async def commit(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        await self._ws.send(json.dumps({"message_type": "COMMIT"}))
        return await self._receive_json()

    async def commit_until_final(self) -> dict[str, Any]:
        """Commit and consume interim/ack events until the final transcript."""
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        await self._ws.send(json.dumps({"message_type": "COMMIT"}))
        while True:
            event = await self._receive_json()
            if event.get("message_type") == "COMMITTED_TRANSCRIPT":
                return event
            if event.get("message_type") in {
                "ERROR", "INPUT_ERROR", "AUTHENTICATION_ERROR", "RESOURCE_EXHAUSTED",
                "QUOTA_EXCEEDED", "CHUNK_SIZE_TOO_SMALL", "CHUNCK_SIZE_TOO_SMALL", "CHUNK_SIZE_TOO_LARGE",
                "INSUFFICIENT_AUDIO_ACTIVITY", "SESSION_TIME_LIMIT_EXCEEDED",
                "CHUNK_ID_MISMATCH_WITH_TOTAL",
            }:
                raise IntronProtocolError(f"Intron terminal error: {event.get('message_type')}")

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _receive_json(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raise IntronProtocolError("Expected JSON text response from Intron")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise IntronProtocolError("Intron response was not a JSON object")
        return data
