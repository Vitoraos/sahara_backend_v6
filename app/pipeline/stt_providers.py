from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Protocol

import websockets
from websockets.asyncio.client import ClientConnection, connect

from app.config import get_settings
from app.pipeline.intron_stream import IntronConfig, IntronSTTStream


class STTProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes) -> str: ...


class StreamingSTTProvider(Protocol):
    name: str

    async def connect(self) -> None: ...
    async def send_audio(self, audio: bytes, ack_id: int | None = None) -> int: ...
    async def receive_event(self) -> dict[str, Any]: ...
    async def commit(self) -> str: ...
    async def close(self) -> None: ...


class IntronStreamingSTT:
    name = "intron"

    def __init__(self, config: IntronConfig) -> None:
        self._stream = IntronSTTStream(config)

    async def connect(self) -> None:
        await self._stream.connect()

    async def send_audio(self, audio: bytes, ack_id: int | None = None) -> int:
        return await self._stream.send_audio(audio, ack_id=ack_id)

    async def receive_event(self) -> dict[str, Any]:
        return await self._stream.receive()

    async def commit(self) -> str:
        event = await self._stream.commit()
        message_type = event.get("message_type")
        if message_type != "COMMITTED_TRANSCRIPT":
            raise RuntimeError(f"Expected COMMITTED_TRANSCRIPT, got {message_type}")
        return _transcript_from_event(event)

    async def close(self) -> None:
        await self._stream.close()


def _transcript_from_event(event: dict[str, Any]) -> str:
    for key in ("transcript", "text", "committed_transcript"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    raise RuntimeError("Intron committed transcript payload has no recognized text field")


class SaharaStreamingSTT:
    """Sahara Voice API Streaming STT Provider.
    
    Implements the Sahara Voice API WebSocket-based STT protocol for real-time voice agents.
    Based on the Intron Voice API documentation patterns.
    """
    
    name = "sahara"

    def __init__(self, api_key: str, endpoint: str = "wss://infer.voice.intron.io/stt/v1/stream",
                 language: str = "en", sample_rate: int = 16000, bit_rate: int = 16, 
                 num_channels: int = 1) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._language = language
        self._sample_rate = sample_rate
        self._bit_rate = bit_rate
        self._num_channels = num_channels
        self._ws: ClientConnection | None = None
        self._next_ack_id = 1

    def _url(self) -> str:
        params = (
            f"sample_rate={self._sample_rate}"
            f"&bit_rate={self._bit_rate}"
            f"&num_channels={self._num_channels}"
            f"&use_language_asr_input={self._language}"
        )
        return f"{self._endpoint}?{params}"

    async def connect(self) -> None:
        self._next_ack_id = 1
        self._ws = await connect(
            self._url(),
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
            open_timeout=10,
        )
        message = await self._receive_json()
        if message.get("message_type") != "SESSION_CREATED":
            raise RuntimeError(f"Expected SESSION_CREATED, got {message.get('message_type')}")

    async def send_audio(self, pcm16le: bytes, ack_id: int | None = None) -> int:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        if not 1024 <= len(pcm16le) <= 32768:
            raise ValueError("Sahara audio chunk must be between 1 KB and 32 KB")
        chunk_id = ack_id if ack_id is not None else self._next_ack_id
        self._next_ack_id = max(self._next_ack_id, chunk_id + 1)
        payload = {
            "message_type": "INPUT_AUDIO_CHUNK",
            "audio_base_64": base64.b64encode(pcm16le).decode("ascii"),
            "ack_id": chunk_id,
        }
        await self._ws.send(json.dumps(payload))
        return chunk_id

    async def receive_event(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        return await self._receive_json()

    async def commit(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        await self._ws.send(json.dumps({"message_type": "COMMIT"}))
        return await self._receive_json()

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _receive_json(self) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("STT stream is not connected")
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raise RuntimeError("Expected JSON text response from Sahara STT")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise RuntimeError("Sahara STT response was not a JSON object")
        return data


class SaharaFileUploadSTT:
    """Sahara Voice API File Upload STT Provider.
    
    Implements the Sahara Voice API asynchronous file-upload STT protocol.
    Used for benchmarking and offline transcription.
    """
    
    name = "sahara-file-upload"

    def __init__(self, api_key: str, upload_endpoint: str = "https://infer.voice.intron.io/file/v1/upload",
                 status_endpoint: str = "https://infer.voice.intron.io/file/v1/status") -> None:
        self._api_key = api_key
        self._upload_endpoint = upload_endpoint
        self._status_endpoint = status_endpoint

    async def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an audio file using Sahara's file-upload STT API.
        
        Args:
            audio_path: Path to the audio file (WAV format recommended)
            
        Returns:
            Transcribed text string
            
        Raises:
            RuntimeError: If the transcription fails or times out
        """
        import aiohttp
        
        # Step 1: Upload the file
        upload_url = self._upload_endpoint
        headers = {"Authorization": f"Bearer {self._api_key}"}
        
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        
        # Prepare multipart form data
        data = aiohttp.FormData()
        data.add_field('audio_file_blob', audio_data, 
                       filename='audio.wav', content_type='audio/wav')
        data.add_field('use_language_asr_input', 'en')  # Default to English
        data.add_field('use_category', 'file_category_general')  # Default category
        
        async with aiohttp.ClientSession() as session:
            # Upload file
            async with session.post(upload_url, headers=headers, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"Sahara STT upload failed: {response.status} - {error_text}")
                
                upload_result = await response.json()
                file_id = upload_result.get('file_id')
                if not file_id:
                    raise RuntimeError("No file_id returned from Sahara STT upload")
            
            # Step 2: Poll for completion
            status_url = f"{self._status_endpoint}/{file_id}"
            max_attempts = 30  # 30 seconds timeout with 1-second intervals
            
            for attempt in range(max_attempts):
                await asyncio.sleep(1)  # Wait between polls
                
                async with session.get(status_url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"Sahara STT status check failed: {response.status} - {error_text}")
                    
                    status_result = await response.json()
                    status = status_result.get('status', '').lower()
                    
                    if status == 'completed':
                        transcript = status_result.get('transcript', '')
                        if not transcript:
                            raise RuntimeError("Completed transcription returned empty text")
                        return transcript
                    elif status == 'failed':
                        error_msg = status_result.get('error', 'Unknown error')
                        raise RuntimeError(f"Sahara STT transcription failed: {error_msg}")
                    # If still processing, continue polling
            
            raise RuntimeError("Sahara STT transcription timed out")


def _sahara_transcript_from_event(event: dict[str, Any]) -> str:
    """Extract transcript from Sahara STT event.
    
    Sahara STT events may have different field names than Intron.
    """
    for key in ("transcript", "text", "committed_transcript"):
        value = event.get(key)
        if isinstance(value, str):
            return value.strip()
    raise RuntimeError("Sahara STT event payload has no recognized text field")
