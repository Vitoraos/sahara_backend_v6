from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

from app.config import Settings


class TranslationProvider(Protocol):
    async def to_english(self, transcript: str) -> str: ...


class TranslationProviderError(RuntimeError):
    pass


class NllbTranslationProvider:
    """Calls a configured translation gateway backed by an African-language-capable model.

    The gateway contract is deliberately explicit because the supplied project spec does not
    name a single hosted NLLB endpoint. It accepts automatic source-language detection and
    returns English text. Translation remains safety-path-only.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def to_english(self, transcript: str) -> str:
        if not self._settings.translation_api_url:
            raise TranslationProviderError("TRANSLATION_API_URL is not configured")
        headers = {"content-type": "application/json"}
        if self._settings.translation_api_key:
            headers["authorization"] = f"Bearer {self._settings.translation_api_key}"
        payload: dict[str, Any] = {
            "text": transcript,
            "source_language": "auto",
            "target_language": "eng_Latn",
        }
        last_error: Exception | None = None
        for attempt in range(self._settings.external_max_retries + 1):
            try:
                timeout = httpx.Timeout(self._settings.external_timeout_seconds)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self._settings.translation_api_url,
                        headers=headers,
                        json=payload,
                    )
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"Translation temporary HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                data = response.json()
                translated = _extract_translation(data)
                if not translated:
                    raise TranslationProviderError("Translation response contained empty text")
                return translated
            except (httpx.HTTPError, TranslationProviderError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt >= self._settings.external_max_retries:
                    break
                await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise TranslationProviderError("Translation request failed") from last_error


def _extract_translation(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("translation", "translated_text", "text"):
            value = data.get(key)
            if isinstance(value, str):
                return value.strip()
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for key in ("translation_text", "translation", "translated_text", "text"):
                value = first.get(key)
                if isinstance(value, str):
                    return value.strip()
    raise TranslationProviderError("Unsupported translation response shape")
