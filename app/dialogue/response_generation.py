from __future__ import annotations

from typing import Protocol

from app.dialogue.field_schema import ExtractedFields
from app.dialogue.language_policy import LanguageProfile
from app.dialogue.state_machine import ConversationState


class ResponseGenerator(Protocol):
    async def generate(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> str: ...


class SafeFallbackResponseGenerator:
    """Non-clinical fallback. Real LLM generation must be injected separately."""

    async def generate(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> str:
        if state == ConversationState.ESCALATE:
            return "I need to connect you with a healthcare professional now. Please stay on the line."
        if state == ConversationState.TRIAGE:
            return "Thank you. I have enough information to continue your triage."
        return "Thank you. I need a little more information before I can continue."
