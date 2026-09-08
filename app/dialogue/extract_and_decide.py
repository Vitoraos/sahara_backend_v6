import asyncio
from typing import Protocol

from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.field_schema import ExtractedFields
from app.dialogue.language_policy import LanguageSignal
from app.dialogue.translation import TranslationProvider


class ExtractionProvider(Protocol):
    async def extract(self, transcript: str) -> ExtractedFields:
        ...


async def extract_and_safety_check(
    transcript: str,
    *,
    extraction_provider: ExtractionProvider,
    translation_provider: TranslationProvider,
    danger_matcher: DangerMatcher,
) -> tuple[ExtractedFields, bool, str]:
    """Run extraction and safety translation concurrently.

    If translation fails, the exception intentionally propagates so the caller
    can apply the required fail-safe escalation path.
    """
    extracted, translated = await asyncio.gather(
        extraction_provider.extract(transcript),
        translation_provider.to_english(transcript),
    )
    match = danger_matcher.match(translated)
    return extracted, match.matched, translated
