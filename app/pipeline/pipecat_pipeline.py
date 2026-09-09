from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.extract_and_decide import ExtractionProvider, extract_and_safety_check
from app.dialogue.field_schema import ExtractedFields
from app.dialogue.language_policy import LanguageProfile, LanguageSignal
from app.dialogue.response_generation import ResponseGenerator
from app.dialogue.state_machine import ConversationState
from app.dialogue.triage_engine import TriageEngine
from app.dialogue.translation import TranslationProvider


@dataclass
class PipelineTurn:
    transcript: str
    translated_text: str
    extracted_fields: ExtractedFields
    danger_sign_fired: bool
    danger_phrases: tuple[str, ...]
    state: ConversationState
    response_text: str
    urgency_tier: str | None = None
    triage_summary: str | None = None


@dataclass
class ConversationContext:
    profile: LanguageProfile = field(default_factory=LanguageProfile.empty)
    state: ConversationState = ConversationState.COLLECTING
    turn_number: int = 0
    fields: dict[str, Any] = field(default_factory=dict)


RequiredFieldsChecker = Callable[[ExtractedFields], bool | Awaitable[bool]]


class ConversationPipeline:
    """Safety-first orchestration independent of a specific LLM or TTS vendor."""

    def __init__(
        self,
        *,
        extraction_provider: ExtractionProvider,
        translation_provider: TranslationProvider,
        danger_matcher: DangerMatcher,
        response_generator: ResponseGenerator,
        required_fields_checker: RequiredFieldsChecker,
        triage_engine: TriageEngine | None = None,
    ) -> None:
        self._extractor = extraction_provider
        self._translator = translation_provider
        self._danger_matcher = danger_matcher
        self._response_generator = response_generator
        self._required_fields_checker = required_fields_checker
        self._triage_engine = triage_engine or TriageEngine()

    async def process_turn(self, transcript: str, context: ConversationContext) -> PipelineTurn:
        context.turn_number += 1
        try:
            extracted, danger_fired, translated = await extract_and_safety_check(
                transcript,
                extraction_provider=self._extractor,
                translation_provider=self._translator,
                danger_matcher=self._danger_matcher,
            )
            # Required fields accumulate across turns. Never let a later turn erase
            # information already collected.
            context.fields.update(extracted.fields)
            accumulated = ExtractedFields(
                fields=dict(context.fields),
                detected_language=extracted.detected_language,
            )
            required = self._required_fields_checker(accumulated)
            required_complete = await required if asyncio.iscoroutine(required) else required
            decision = self._triage_engine.decide(
                required_fields_complete=required_complete,
                danger_sign_fired=danger_fired,
            )
            context.state = decision.state
            signal = _language_signal(extracted)
            context.profile.update(signal)
            response = await self._response_generator.generate(
                transcript=transcript,
                fields=accumulated,
                state=decision.state,
                language_profile=context.profile,
            )
            match = self._danger_matcher.match(translated)
            urgency = "RED" if danger_fired else ("AMBER" if decision.state == ConversationState.TRIAGE else None)
            summary = _triage_summary(accumulated, match.matched_phrases) if decision.state == ConversationState.TRIAGE else None
            return PipelineTurn(
                transcript=transcript,
                translated_text=translated,
                extracted_fields=accumulated,
                danger_sign_fired=danger_fired,
                danger_phrases=match.matched_phrases,
                state=decision.state,
                response_text=response,
                urgency_tier=urgency,
                triage_summary=summary,
            )
        except Exception as exc:
            # Fail-safe: any mid-turn failure escalates. Never silently continue.
            context.state = ConversationState.ESCALATE
            logger = logging.getLogger(__name__)
            logger.exception(
                "conversation turn failed; escalating",
                extra={"turn_number": context.turn_number, "error_type": type(exc).__name__},
            )
            return PipelineTurn(
                transcript=transcript,
                translated_text="",
                extracted_fields=ExtractedFields(),
                danger_sign_fired=False,
                danger_phrases=(),
                state=ConversationState.ESCALATE,
                response_text="I need to connect you with a healthcare professional now. Please stay on the line.",
            )

    async def process_turn_stream(
        self,
        transcript: str,
        context: ConversationContext,
    ) -> tuple[PipelineTurn, AsyncIterator[str]]:
        """Process one turn and stream the LLM response text as it arrives.

        Returns the final PipelineTurn (for persistence and UI) plus an async
        iterator that yields response text chunks as the LLM produces them.
        """
        context.turn_number += 1
        extracted, danger_fired, translated = await extract_and_safety_check(
            transcript,
            extraction_provider=self._extractor,
            translation_provider=self._translator,
            danger_matcher=self._danger_matcher,
        )
        # Required fields accumulate across turns. Never let a later turn erase
        # information already collected.
        context.fields.update(extracted.fields)
        accumulated = ExtractedFields(
            fields=dict(context.fields),
            detected_language=extracted.detected_language,
        )
        required = self._required_fields_checker(accumulated)
        required_complete = await required if asyncio.iscoroutine(required) else required
        decision = self._triage_engine.decide(
            required_fields_complete=required_complete,
            danger_sign_fired=danger_fired,
        )
        context.state = decision.state
        signal = _language_signal(extracted)
        context.profile.update(signal)

        async def response_stream() -> AsyncIterator[str]:
            try:
                async for chunk in self._response_generator.generate_stream(
                    transcript=transcript,
                    fields=accumulated,
                    state=decision.state,
                    language_profile=context.profile,
                ):
                    yield chunk
            except Exception as exc:
                # Fail-safe: any mid-turn failure escalates. Never silently continue.
                logger = logging.getLogger(__name__)
                logger.exception(
                    "conversation turn failed; escalating",
                    extra={"turn_number": context.turn_number, "error_type": type(exc).__name__},
                )
                context.state = ConversationState.ESCALATE
                yield "I need to connect you with a healthcare professional now. Please stay on the line."

        match = self._danger_matcher.match(translated)
        urgency = "RED" if danger_fired else ("AMBER" if decision.state == ConversationState.TRIAGE else None)
        summary = _triage_summary(accumulated, match.matched_phrases) if decision.state == ConversationState.TRIAGE else None
        final_response = "".join(response_stream)
        response_text = final_response.strip()
        return PipelineTurn(
            transcript=transcript,
            translated_text=translated,
            extracted_fields=accumulated,
            danger_sign_fired=danger_fired,
            danger_phrases=match.matched_phrases,
            state=decision.state,
            response_text=response_text,
            urgency_tier=urgency,
            triage_summary=summary,
        ), response_stream()



def _triage_summary(fields: ExtractedFields, danger_phrases: tuple[str, ...]) -> str:
    parts = []
    complaint = fields.fields.get("chief_complaint")
    if complaint:
        parts.append(f"Chief complaint: {complaint}")
    symptoms = fields.fields.get("symptoms")
    if symptoms:
        parts.append(f"Symptoms: {symptoms}")
    onset = fields.fields.get("symptom_onset")
    if onset:
        parts.append(f"Onset: {onset}")
    severity = fields.fields.get("symptom_severity")
    if severity:
        parts.append(f"Severity: {severity}")
    if danger_phrases:
        parts.append(f"Safety indicators: {', '.join(danger_phrases)}")
    return "; ".join(parts) or "Triage completed; clinician review required."


def _language_signal(fields: ExtractedFields) -> LanguageSignal:
    raw = fields.detected_language.get("languages", ())
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (list, tuple)):
        raw = ()
    languages = tuple(str(language) for language in raw if language)
    confidence = fields.detected_language.get("confidence")
    return LanguageSignal(languages=languages, confidence=confidence if isinstance(confidence, (int, float)) else None)

