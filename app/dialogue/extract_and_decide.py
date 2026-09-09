from typing import Protocol

from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.field_schema import ExtractedFields


class ExtractionProvider(Protocol):
    async def extract(self, transcript: str) -> ExtractedFields:
        ...


async def extract_and_safety_check(
    transcript: str,
    *,
    extraction_provider: ExtractionProvider,
    danger_matcher: DangerMatcher,
) -> tuple[ExtractedFields, bool, str]:
    extracted = await extraction_provider.extract(transcript)
    match = danger_matcher.match(transcript)
    return extracted, match.matched, transcript