import pytest

from app.dialogue.field_schema import ExtractedFields
from app.dialogue.voice_map import normalize_code, resolve_voice
from app.pipeline.intron_stream import _is_not_ready as _stt_not_ready
from app.pipeline.intron_tts import _is_not_ready as _tts_not_ready
from app.pipeline.pipecat_pipeline import ConversationContext, ConversationPipeline, maybe_lock_voice
from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.response_generation import SafeFallbackResponseGenerator


def detected(*languages: str, confidence: float = 0.9) -> ExtractedFields:
    return ExtractedFields(detected_language={"languages": list(languages), "confidence": confidence})


def test_normalize_code():
    assert normalize_code("Hausa") == "ha"
    assert normalize_code(" HA ") == "ha"
    assert normalize_code("pcm") == "pcm"
    assert normalize_code("xx") is None
    assert normalize_code("") is None
    assert normalize_code(None) is None
    assert normalize_code(123) is None


def test_resolve_voice():
    assert resolve_voice("ha", default_accent="yoruba") == ("ha", "hausa")
    assert resolve_voice("yo", default_accent="yoruba") == ("yo", "yoruba")
    assert resolve_voice("en", default_accent="swahili") == ("en", "swahili")


def test_not_ready_detection():
    cold = {"message_type": "RESOURCE_EXHAUSTED", "status": "NOT_READY", "message": "Required language not available, please wait 30 seconds"}
    assert _stt_not_ready(cold) is True
    assert _tts_not_ready(cold) is True
    assert _stt_not_ready({"message_type": "SESSION_CREATED"}) is False
    assert _stt_not_ready({"message_type": "AUTHENTICATION_ERROR"}) is False


@pytest.mark.asyncio
async def test_phone_session_language_prefers_last_confident_turn():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.routes.voice_webhook import _session_language

    settings = SimpleNamespace(voice_lock_confidence=0.6)

    class Repo:
        async def patient_by_id(self, patient_id):
            return {"preferred_language": "ha"}

        async def last_turn_language(self, conversation_id):
            return {"languages": ["yo"], "confidence": 0.9}

    assert await _session_language(Repo(), uuid4(), uuid4(), settings) == "yo"

    class QuietRepo(Repo):
        async def last_turn_language(self, conversation_id):
            return {"languages": ["yo"], "confidence": 0.1}

    assert await _session_language(QuietRepo(), uuid4(), uuid4(), settings) == "ha"

    class EmptyRepo(Repo):
        async def last_turn_language(self, conversation_id):
            return {}

    assert await _session_language(EmptyRepo(), uuid4(), uuid4(), settings) == "ha"


def test_lock_switches_once_then_never():
    context = ConversationContext(session_language="en")
    assert maybe_lock_voice(context, detected("Hausa")) == "ha"
    assert context.session_language == "ha"
    assert context.voice_locked is True
    # A later turn in another language cannot switch again.
    assert maybe_lock_voice(context, detected("yo")) is None
    assert context.session_language == "ha"


def test_lock_without_switch_when_same():
    context = ConversationContext(session_language="ha")
    assert maybe_lock_voice(context, detected("ha")) is None
    assert context.voice_locked is True


def test_no_lock_below_threshold_or_unknown():
    context = ConversationContext(session_language="en")
    assert maybe_lock_voice(context, detected("ha", confidence=0.1)) is None
    assert context.voice_locked is False
    assert maybe_lock_voice(context, detected("Klingon")) is None
    assert context.voice_locked is False


class HaExtractor:
    async def extract(self, transcript: str) -> ExtractedFields:
        return detected("ha")


@pytest.mark.asyncio
async def test_process_turn_reports_switch():
    pipeline = ConversationPipeline(
        extraction_provider=HaExtractor(),
        danger_matcher=DangerMatcher(()),
        response_generator=SafeFallbackResponseGenerator(),
        required_fields_checker=lambda _: True,
    )
    context = ConversationContext(session_language="en")
    result = await pipeline.process_turn("anything", context)
    assert result.session_language == "ha"
    assert context.session_language == "ha"


@pytest.mark.asyncio
async def test_process_turn_no_switch_when_preferred_matches():
    pipeline = ConversationPipeline(
        extraction_provider=HaExtractor(),
        danger_matcher=DangerMatcher(()),
        response_generator=SafeFallbackResponseGenerator(),
        required_fields_checker=lambda _: True,
    )
    context = ConversationContext(session_language="ha")
    result = await pipeline.process_turn("anything", context)
    assert result.session_language is None
    assert context.voice_locked is True
