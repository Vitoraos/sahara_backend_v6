from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings


class AfricasTalkingClient:
    """Minimal async Africa's Talking Voice API client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._url = "https://voice.africastalking.com/call"

    async def initiate_call(self, from_number: str, to_number: str) -> str:
        if not self._settings.africas_talking_username or not self._settings.africas_talking_api_key:
            raise RuntimeError("Africa's Talking credentials are not configured")
        data = {"username": self._settings.africas_talking_username, "from": from_number, "to": to_number}
        headers = {"apiKey": self._settings.africas_talking_api_key, "Accept": "application/json"}
        last_error: Exception | None = None
        for attempt in range(self._settings.external_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._settings.external_timeout_seconds) as client:
                    response = await client.post(self._url, data=data, headers=headers)
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError("Africa's Talking temporary error", request=response.request, response=response)
                response.raise_for_status()
                payload: Any = response.json()
                if isinstance(payload, dict):
                    entries = payload.get("entries")
                    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                        session_id = entries[0].get("sessionId") or entries[0].get("session_id")
                        if isinstance(session_id, str):
                            return session_id
                    for key in ("sessionId", "session_id"):
                        if isinstance(payload.get(key), str):
                            return payload[key]
                raise RuntimeError("Africa's Talking call response did not include a session id")
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt >= self._settings.external_max_retries:
                    break
                await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise RuntimeError("Africa's Talking call initiation failed") from last_error
