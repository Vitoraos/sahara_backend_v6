import pytest

from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.field_schema import ExtractedFields
from app.dialogue.response_generation import SafeFallbackResponseGenerator
from app.dialogue.translation import TranslationProvider
from app.pipeline.pipecat_pipeline import ConversationContext, ConversationPipeline


class Extractor:
    async def extract(self, transcript: str) -> ExtractedFields:
        return ExtractedFields(detected_language={"languages": ["en"]})


class Translator:
    async def to_english(self, transcript: str) -> str:
        return transcript


class BrokenTranslator:
    async def to_english(self, transcript: str) -> str:
        raise RuntimeError("translation unavailable")


@pytest.mark.asyncio
async def test_danger_path_reaches_triage():
    pipeline = ConversationPipeline(
        extraction_provider=Extractor(),
        translation_provider=Translator(),
        danger_matcher=DangerMatcher(("severe bleeding",)),
        response_generator=SafeFallbackResponseGenerator(),
        required_fields_checker=lambda _: False,
    )
    result = await pipeline.process_turn("patient has severe bleeding", ConversationContext())
    assert result.state.value == "TRIAGE"
    assert result.danger_sign_fired is True


@pytest.mark.asyncio
async def test_translation_failure_is_fail_safe():
    pipeline = ConversationPipeline(
        extraction_provider=Extractor(),
        translation_provider=BrokenTranslator(),
        danger_matcher=DangerMatcher(("severe bleeding",)),
        response_generator=SafeFallbackResponseGenerator(),
        required_fields_checker=lambda _: False,
    )
    result = await pipeline.process_turn("anything", ConversationContext())
    assert result.state.value == "ESCALATE"

class IncrementalExtractor:
    def __init__(self):
        self.i = 0

    async def extract(self, transcript: str) -> ExtractedFields:
        self.i += 1
        if self.i == 1:
            return ExtractedFields(fields={"patient_age": "30", "sex": "female", "chief_complaint": "fever", "symptoms": ["fever"], "symptom_onset": "today", "symptom_severity": "mild"})
        return ExtractedFields(fields={"breathing_difficulty": "no", "consciousness_status": "alert", "seizure_or_convulsion": "no", "ability_to_drink": "yes", "bleeding": "no"})


@pytest.mark.asyncio
async def test_required_fields_accumulate_across_turns():
    extractor = IncrementalExtractor()
    pipeline = ConversationPipeline(
        extraction_provider=extractor,
        translation_provider=Translator(),
        danger_matcher=DangerMatcher(()),
        response_generator=SafeFallbackResponseGenerator(),
        required_fields_checker=lambda fields: all(
            name in fields.fields for name in (
                "patient_age", "sex", "chief_complaint", "symptoms", "symptom_onset",
                "symptom_severity", "breathing_difficulty", "consciousness_status",
                "seizure_or_convulsion", "ability_to_drink", "bleeding",
            )
        ),
    )
    context = ConversationContext()
    first = await pipeline.process_turn("I have fever", context)
    second = await pipeline.process_turn("I can drink and I am alert", context)
    assert first.state.value == "COLLECTING"
    assert second.state.value == "TRIAGE"
