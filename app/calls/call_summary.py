from __future__ import annotations

from app.dialogue.llm_provider import NvidiaClient


class CallSummaryService:
    """Extracts key points from a doctor-patient call transcript for the
    doctor's own record — a structured summary, not a verbatim dump."""

    def __init__(self, client: NvidiaClient) -> None:
        self._client = client

    async def summarize(self, transcript: str) -> str:
        system = (
            "You summarize doctor-patient telehealth call transcripts for the "
            "doctor's own record. Do not diagnose or add clinical opinions not "
            "stated in the call. Extract only: reported symptoms, decisions "
            "made, medications discussed, and agreed follow-up. Keep it under "
            "150 words, in plain clinical shorthand."
        )
        return await self._client.chat_text(system=system, user=transcript, max_tokens=300)
