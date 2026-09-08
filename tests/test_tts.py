import asyncio
import base64
import json

import pytest

from app.pipeline import intron_tts
from app.pipeline.intron_tts import IntronTTSConfig, IntronTTSStream, _audio_from_event, _chunk_text


def test_text_chunking_obeys_intron_bounds():
    chunks = _chunk_text("one two three four five six seven eight nine ten", 100)
    assert all(10 <= len(chunk) <= 100 for chunk in chunks)


def test_audio_event_decodes_base64():
    raw = b"wav-bytes"
    encoded = base64.b64encode(raw).decode()
    assert _audio_from_event({"message_type": "FETCH_AUDIO_CHUNK", "audio_base_64": encoded}) == raw
    assert _audio_from_event({"message_type": "READY_AUDIO_CHUNK", "audio_base_64": encoded}) == raw


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.incoming = asyncio.Queue()

    async def send(self, value: str) -> None:
        message = json.loads(value)
        self.sent.append(message)
        if message["message_type"] == "FETCH_AUDIO_CHUNK":
            await self.incoming.put(
                {
                    "message_type": "FETCH_AUDIO_CHUNK",
                    "processing_status": "READY",
                    "chunk_id": message["chunk_id"],
                    "audio_base_64": base64.b64encode(b"wav").decode(),
                }
            )
        elif message["message_type"] == "COMMIT":
            await self.incoming.put({"message_type": "COMMITTED_AUDIO", "audio_len": 1})

    async def recv(self) -> str:
        return json.dumps(await self.incoming.get())

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_iter_audio_uses_fetch_ready_then_commit(monkeypatch: pytest.MonkeyPatch):
    fake = FakeWebSocket()

    async def fake_connect(*args, **kwargs):
        await fake.incoming.put({"message_type": "SESSION_CREATED"})
        return fake

    monkeypatch.setattr(intron_tts, "connect", fake_connect)
    stream = IntronTTSStream(
        IntronTTSConfig(
            endpoint="wss://example.test",
            api_key="test",
            voice_accent="accent",
            voice_gender="female",
        )
    )

    chunks = [chunk async for chunk in stream.iter_audio("Please tell me your main symptom today.")]
    assert chunks == [b"wav"]
    assert [message["message_type"] for message in fake.sent] == [
        "INPUT_TEXT_CHUNK",
        "FETCH_AUDIO_CHUNK",
        "COMMIT",
    ]
