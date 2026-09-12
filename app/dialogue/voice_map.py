"""Allowed voice languages and the Intron accent each one maps to.

Every supported language has exactly one same-name TTS accent (verified
against Intron's supported-languages-and-accents page), except English,
which uses the deployment default accent. Gender stays env-wide.
"""

from __future__ import annotations

ALLOWED_LANGUAGES: tuple[str, ...] = ("en", "ha", "yo", "ig", "pcm", "sw")

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ha": "Hausa",
    "yo": "Yoruba",
    "ig": "Igbo",
    "pcm": "Pidgin",
    "sw": "Swahili",
}

# language code -> Intron TTS voice_accent. "en" is mapped by the caller to
# the configured default accent (INTRON_TTS_VOICE_ACCENT).
ACCENTS: dict[str, str] = {
    "en": "",
    "ha": "hausa",
    "yo": "yoruba",
    "ig": "igbo",
    "pcm": "pidgin",
    "sw": "swahili",
}

DEFAULT_LANGUAGE = "en"

# Extraction confidence at/above which a detected language locks the session.
LOCK_CONFIDENCE = 0.6


def normalize_code(value: object) -> str | None:
    """Turns free-form LLM output ("Hausa", "HA ") into a canonical code.

    Returns None for anything outside the allow-list so callers fall back
    to the session/default language instead of sending Intron a code it
    will reject.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text in ACCENTS:
        return text
    for code, name in LANGUAGE_NAMES.items():
        if text == name.lower():
            return code
    return None


def resolve_voice(code: str, *, default_accent: str) -> tuple[str, str]:
    """Maps a canonical language code to (voice_language, voice_accent)."""
    if code == "en":
        return "en", default_accent
    return code, ACCENTS[code]
