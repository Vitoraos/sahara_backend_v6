from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import httpx
from app.config import Settings


class STTBenchmarkProvider(Protocol):
    name: str

    async def transcribe_file(self, audio_path: Path) -> str: ...


class SaharaFileUploadSTTProvider:
    """Sahara Voice API File Upload STT Provider.
    
    Implements the Sahara Voice API asynchronous file-upload STT protocol.
    Used for benchmarking and offline transcription.
    """
    
    name = "sahara"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.sahara_api_key
        self._upload_endpoint = "https://infer.voice.intron.io/file/v1/upload"
        self._status_endpoint = "https://infer.voice.intron.io/file/v1/status"

    async def transcribe_file(self, audio_path: Path) -> str:
        """Transcribe an audio file using Sahara's file-upload STT API.
        
        Args:
            audio_path: Path to the audio file (WAV format recommended)
            
        Returns:
            Transcribed text string
            
        Raises:
            RuntimeError: If the transcription fails or times out
        """
        # Step 1: Upload the file
        upload_url = self._upload_endpoint
        headers = {"Authorization": f"Bearer {self._api_key}"}
        
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        
        # Prepare multipart form data
        files = {
            'audio_file_blob': ('audio.wav', audio_data, 'audio/wav')
        }
        data = {
            'use_language_asr_input': 'en',  # Default to English
            'use_category': 'file_category_general'  # Default category
        }
        
        async with httpx.AsyncClient() as client:
            # Upload file
            upload_response = await client.post(
                upload_url, 
                headers=headers, 
                files=files, 
                data=data,
                timeout=30.0
            )
            
            if upload_response.status_code != 200:
                raise RuntimeError(
                    f"Sahara STT upload failed: {upload_response.status_code} - {upload_response.text}"
                )
            
            upload_result = upload_response.json()
            file_id = upload_result.get('file_id')
            if not file_id:
                raise RuntimeError("No file_id returned from Sahara STT upload")
            
            # Step 2: Poll for completion
            status_url = f"{self._status_endpoint}/{file_id}"
            max_attempts = 30  # 30 seconds timeout with 1-second intervals
            
            for attempt in range(max_attempts):
                await asyncio.sleep(1)  # Wait between polls
                
                status_response = await client.get(
                    status_url, 
                    headers=headers,
                    timeout=10.0
                )
                
                if status_response.status_code != 200:
                    raise RuntimeError(
                        f"Sahara STT status check failed: {status_response.status_code} - {status_response.text}"
                    )
                
                status_result = status_response.json()
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


# The challenge requires 3+ models including a Sahara API, plus 2 or more
# others. Add concrete providers for the other two here once hosting is
# decided (e.g. a hosted Whisper large-v3 endpoint, a hosted Meta MMS
# endpoint) — each should implement STTBenchmarkProvider the same way.

class GroqWhisperSTTProvider:
    """Groq-hosted Whisper STT Provider for benchmarking.
    
    Uses Groq's Whisper Large v3 endpoint via OpenAI-compatible API.
    """
    
    name = "groq-whisper"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.groq_api_key  # Would need to add to Settings
        self._endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe_file(self, audio_path: Path) -> str:
        """Transcribe an audio file using Groq's Whisper API."""
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY not configured")
        
        headers = {"Authorization": f"Bearer {self._api_key}"}
        
        with open(audio_path, 'rb') as f:
            files = {
                'file': ('audio.wav', f.read(), 'audio/wav')
            }
            data = {
                'model': 'whisper-large-v3',
                'response_format': 'text'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._endpoint,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Groq Whisper transcription failed: {response.status_code} - {response.text}"
                    )
                
                return response.text.strip()


class HuggingFaceMMSSTTProvider:
    """Hugging Face Inference API MMS STT Provider for benchmarking.
    
    Uses a hosted MMS (Massively Multilingual Speech) model via HF Inference API.
    """
    
    name = "hf-mms"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.hf_api_key  # Would need to add to Settings
        self._endpoint = "https://api-inference.huggingface.co/models/facebook/mms-1b-all"

    async def transcribe_file(self, audio_path: Path) -> str:
        """Transcribe an audio file using Hugging Face MMS API."""
        if not self._api_key:
            raise RuntimeError("HF_API_KEY not configured")
        
        headers = {"Authorization": f"Bearer {self._api_key}"}
        
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoint,
                headers=headers,
                data=audio_data,
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise RuntimeError(
                    f"HF MMS transcription failed: {response.status_code} - {response.text}"
                )
            
            result = response.json()
            # MMS API returns either direct text or a list with text
            if isinstance(result, dict) and 'text' in result:
                return result['text'].strip()
            elif isinstance(result, list) and len(result) > 0 and 'text' in result[0]:
                return result[0]['text'].strip()
            else:
                # Assume direct text response
                return str(result).strip()
