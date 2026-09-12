from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.dialogue.field_schema import ExtractedFields
from app.dialogue.language_policy import LanguageProfile
from app.dialogue.state_machine import ConversationState


class ProviderError(RuntimeError):
    """An external provider failed or returned unusable response."""


_shared_http: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    # ponytail: one keep-alive client per process skips TLS+TCP setup on
    # every LLM call; recreate it if the event loop ever turns over.
    global _shared_http
    if _shared_http is None:
        _shared_http = httpx.AsyncClient()
    return _shared_http


class OpenRouterClient:
    """Async OpenRouter client with streaming support.

    OpenRouter (https://openrouter.ai/api/v1) is OpenAI-compatible —
    same chat.completions request/response shape as OpenAI, with streaming
    via Server-Sent Events (SSE). Set "stream": true to receive incremental
    responses.
    """

    def __init__(self, settings: Settings, model: str) -> None:
        self._settings = settings
        self._url = settings.openrouter_api_url
        self._model = model

    async def chat(self, *, system: str, user: str, max_tokens: int = 512) -> dict[str, Any]:
        """Non-streaming chat completion."""
        if not self._settings.openrouter_api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(self._settings.external_max_retries + 1):
            try:
                timeout = httpx.Timeout(self._settings.external_timeout_seconds)
                response = await _http().post(self._url, headers=headers, json=payload, timeout=timeout)
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"OpenRouter temporary HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ProviderError("OpenRouter response was not an object")
                return data
            except (httpx.HTTPError, ProviderError) as exc:
                last_error = exc
                if attempt >= self._settings.external_max_retries:
                    break
                await _backoff(attempt)
        raise ProviderError("OpenRouter request failed") from last_error

    async def chat_stream(self, *, system: str, user: str, max_tokens: int = 512) -> AsyncIterator[str]:
        """Streaming chat completion - yields text chunks as they arrive."""
        if not self._settings.openrouter_api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured")
        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(self._settings.external_max_retries + 1):
            try:
                timeout = httpx.Timeout(self._settings.external_timeout_seconds)
                async with _http().stream("POST", self._url, headers=headers, json=payload, timeout=timeout) as response:
                        if response.status_code >= 500 or response.status_code == 429:
                            raise httpx.HTTPStatusError(
                                f"OpenRouter temporary HTTP {response.status_code}",
                                request=response.request,
                                response=response,
                            )
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]  # Remove "data: "
                            if data_str.strip() == "[DONE]":
                                return
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices")
                                if not isinstance(choices, list) or not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                if isinstance(content, str) and content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                return  # Success
            except (httpx.HTTPError, ProviderError) as exc:
                last_error = exc
                if attempt >= self._settings.external_max_retries:
                    break
                await _backoff(attempt)
        raise ProviderError("OpenRouter streaming request failed") from last_error

    async def chat_text(self, *, system: str, user: str, max_tokens: int = 512) -> str:
        """Convenience wrapper: chat() + text extraction in one call."""
        return _text_from_openrouter(await self.chat(system=system, user=user, max_tokens=max_tokens))

    async def chat_text_stream(self, *, system: str, user: str, max_tokens: int = 512) -> AsyncIterator[str]:
        """Convenience wrapper: chat_stream() yielding text chunks."""
        async for chunk in self.chat_stream(system=system, user=user, max_tokens=max_tokens):
            yield chunk


async def _backoff(attempt: int) -> None:
    await asyncio.sleep(min(0.25 * (2**attempt), 1.0))


def _text_from_openrouter(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("OpenRouter response has no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("OpenRouter response contains no text")
    return text.strip()


class OpenRouterExtractionProvider:
    """Extracts only the configured field names plus language metadata."""

    def __init__(self, client: OpenRouterClient, allowed_fields: tuple[str, ...]) -> None:
        self._client = client
        self._allowed_fields = allowed_fields

    async def extract(self, transcript: str) -> ExtractedFields:
        field_list = ", ".join(self._allowed_fields) if self._allowed_fields else "(none configured)"
        system = (
            "You are a structured data extractor for a health triage voice agent. "
            "Do not diagnose, prescribe, or invent facts. Extract only information explicitly "
            "present in the patient utterance. Return ONLY valid JSON with this shape: "
            '{"fields": {"field_name": "value"}, "detected_language": '
            '{"languages": ["en"|"ha"|"yo"|"ig"|"pcm"|"sw"], "confidence": 0.0}}. '
            "Use only those ISO codes for detected languages (English, Hausa, "
            "Yoruba, Igbo, Pidgin, Swahili). "
            f"Allowed field names: {field_list}. Unknown information must be omitted."
        )
        raw = await self._client.chat_text(system=system, user=transcript, max_tokens=400)
        try:
            data = json.loads(_strip_code_fence(raw))
            return ExtractedFields.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ProviderError("OpenRouter extraction returned invalid structured data") from exc


class OpenRouterResponseGenerator:
    """Generates conversational responses using OpenRouter with streaming support."""

    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    async def generate(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> str:
        """Non-streaming generation - returns complete response."""
        languages = ", ".join(language_profile.dominant_languages()) or "match the patient"
        system = (
            "You are a conversational health triage assistant. Do not diagnose or prescribe. "
            "Ask concise questions needed for triage. If escalation is required, clearly tell "
            "the patient that a healthcare professional needs to be contacted now. Respond in "
            f"the patient's established language style: {languages}. Current state: {state.value}."
        )
        user = f"Patient said: {transcript}\nStructured fields: {json.dumps(fields.fields, ensure_ascii=False)}"
        return await self._client.chat_text(system=system, user=user, max_tokens=300)

    async def generate_stream(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> AsyncIterator[str]:
        """Streaming generation - yields text chunks as they arrive."""
        languages = ", ".join(language_profile.dominant_languages()) or "match the patient"
        system = (
            "You are a conversational health triage assistant. Do not diagnose or prescribe. "
            "Ask concise questions needed for triage. If escalation is required, clearly tell "
            "the patient that a healthcare professional needs to be contacted now. Respond in "
            f"the patient's established language style: {languages}. Current state: {state.value}."
        )
        user = f"Patient said: {transcript}\nStructured fields: {json.dumps(fields.fields, ensure_ascii=False)}"
        async for chunk in self._client.chat_text_stream(system=system, user=user, max_tokens=300):
            yield chunk


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return text


# Backward compatibility aliases
NvidiaClient = OpenRouterClient
NvidiaExtractionProvider = OpenRouterExtractionProvider
NvidiaResponseGenerator = OpenRouterResponseGenerator