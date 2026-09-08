from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageSignal:
    languages: tuple[str, ...]
    confidence: float | None = None


@dataclass
class LanguageProfile:
    counts: Counter[str]

    @classmethod
    def empty(cls) -> 'LanguageProfile':
        return cls(counts=Counter())

    def update(self, signal: LanguageSignal) -> None:
        self.counts.update(signal.languages)

    def dominant_languages(self) -> tuple[str, ...]:
        return tuple(language for language, _ in self.counts.most_common())


class LanguagePolicy:
    def update_and_get_response_style(
        self,
        profile: LanguageProfile,
        signal: LanguageSignal,
    ) -> str:
        profile.update(signal)
        dominant = profile.dominant_languages()
        if not dominant:
            return 'match_patient_language_profile'
        return 'respond_using_dominant_or_code_switched_profile:' + ','.join(dominant)
