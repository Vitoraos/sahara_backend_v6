from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DangerMatch:
    matched: bool
    matched_phrases: tuple[str, ...] = ()


class DangerMatcher:
    """Deterministic English safety gate with simple negation handling.

    Translation is the only input accepted by the caller. We deliberately keep
    the final decision deterministic; an LLM may extract context but cannot
    disable this gate.
    """

    _NEGATION = re.compile(r"\b(?:no|not|never|without|don't|do not|doesn't|does not|didn't|did not)\b")

    def __init__(self, phrases: tuple[str, ...] = ()) -> None:
        self._phrases = tuple(p.strip().lower() for p in phrases if p.strip())

    def match(self, translated_english: str) -> DangerMatch:
        normalized = re.sub(r"\s+", " ", translated_english.lower()).strip()
        matches: list[str] = []
        for phrase in self._phrases:
            start = 0
            while True:
                index = normalized.find(phrase, start)
                if index < 0:
                    break
                prefix = normalized[max(0, index - 60):index]
                if not self._negated(prefix):
                    matches.append(phrase)
                    break
                start = index + len(phrase)
        return DangerMatch(matched=bool(matches), matched_phrases=tuple(dict.fromkeys(matches)))

    @classmethod
    def _negated(cls, prefix: str) -> bool:
        tokens = re.findall(r"[a-z']+", prefix)
        window = tokens[-5:]
        return any(token in {"no", "not", "never", "without", "don't", "do", "doesn't", "does", "didn't", "did"} for token in window)
