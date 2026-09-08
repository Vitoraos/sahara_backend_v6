from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.integrations.conversation_repository import ConversationRepository


class ConsentRequiredError(Exception):
    pass


class CallRecorder:
    """Consent-gated lifecycle for a doctor-patient call recording.

    Per RULES.md rule 4: recording never starts without explicit recorded
    consent, and the consent event itself is persisted alongside the
    recording row — never recorded silently.
    """

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    async def start(self, *, appointment_id: UUID, consent_recorded: bool) -> dict[str, Any]:
        if not consent_recorded:
            raise ConsentRequiredError(
                "Explicit recorded consent is required before recording starts."
            )
        return await self._repository.create_call_recording(
            appointment_id=appointment_id,
            consent_recorded_at=datetime.now(timezone.utc).isoformat(),
        )

    async def attach_recording_url(self, *, call_recording_id: UUID, recording_url: str) -> None:
        """Called once the call provider's recording artifact is ready."""
        await self._repository.update_call_recording(
            call_recording_id=call_recording_id,
            recording_url=recording_url,
        )

    async def attach_transcript_and_summary(
        self, *, call_recording_id: UUID, transcript: str, key_points_summary: str
    ) -> None:
        await self._repository.update_call_recording(
            call_recording_id=call_recording_id,
            transcript=transcript,
            key_points_summary=key_points_summary,
        )
