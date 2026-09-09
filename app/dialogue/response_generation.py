from __future__ import annotations

from typing import AsyncIterator, Protocol

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

    async def generate_stream(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> AsyncIterator[str]: ...


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

    async def generate_stream(
        self,
        *,
        transcript: str,
        fields: ExtractedFields,
        state: ConversationState,
        language_profile: LanguageProfile,
    ) -> AsyncIterator[str]:
        """Stream fallback response word by word for compatibility."""
        text = await self.generate(
            transcript=transcript,
            fields=fields,
            state=state,
            language_profile=language_profile,
        )
        # Yield in small chunks to simulate streaming
        for word in text.split():
            yield word + " "
            await asyncio.sleep(0.01)
