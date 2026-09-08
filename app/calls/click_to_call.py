from __future__ import annotations

from app.config import Settings
from app.integrations.africas_talking import AfricasTalkingClient


class ClickToCallService:
    """Thin wrapper over Africa's Talking Voice for bridging two numbers."""

    def __init__(self, settings: Settings) -> None:
        self._client = AfricasTalkingClient(settings)

    async def bridge(self, from_number: str, to_number: str) -> str:
        """Initiates an outbound call bridging two numbers. Returns the
        provider's session id."""
        if not from_number:
            raise RuntimeError("No outbound calling number configured")
        return await self._client.initiate_call(from_number=from_number, to_number=to_number)
