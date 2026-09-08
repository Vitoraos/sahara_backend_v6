from __future__ import annotations

import html
import hmac
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.config import Settings, get_settings
from app.dialogue.danger_matcher import DangerMatcher
from app.dialogue.field_schema import RequiredFieldPolicy
from app.dialogue.llm_provider import NvidiaClient, NvidiaExtractionProvider, NvidiaResponseGenerator
from app.dialogue.response_generation import SafeFallbackResponseGenerator
from app.dialogue.translation import NllbTranslationProvider
from app.integrations.conversation_repository import ConversationRepository
from app.integrations.supabase_client import create_supabase
from app.pipeline.intron_stream import IntronConfig, IntronSTTStream
from app.pipeline.pipecat_pipeline import ConversationContext, ConversationPipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice"])


def _xml(*actions: str) -> Response:
    body = '<?xml version="1.0" encoding="UTF-8"?>' + "<Response>" + "".join(actions) + "</Response>"
    return Response(content=body, media_type="application/xml")


def _say(text: str) -> str:
    return f"<Say>{html.escape(text)}</Say>"


def _record(callback_url: str, *, max_length: int) -> str:
    return (
        f'<Record finishOnKey="#" trimSilence="true" playBeep="true" '
        f'maxLength="{max_length}" callbackUrl="{html.escape(callback_url, quote=True)}"/>'
    )


def _callback_base(settings: Settings) -> str:
    if not settings.base_url:
        raise RuntimeError("BASE_URL is required for the phone channel")
    return settings.base_url.rstrip("/")


def _webhook_authorized(request: Request, settings: Settings) -> bool:
    if not settings.africas_talking_webhook_secret:
        return True
    supplied = request.headers.get("x-webhook-secret", "")
    return hmac.compare_digest(supplied, settings.africas_talking_webhook_secret)


@router.post("/voice/webhook")
async def voice_webhook(request: Request) -> Response:
    """Africa's Talking inbound-call callback.

    AT's documented Voice API is callback/XML based; the phone channel therefore
    uses short recorded turns. Each recording is processed by the same STT ->
    safety/triage -> response logic as the browser agent. Real-time media streaming
    requires an RTP/SIP bridge; this endpoint intentionally does not pretend AT's
    XML callback is a raw media WebSocket.
    """
    form = await request.form()
    caller = str(form.get("callerNumber") or form.get("phoneNumber") or "").strip()
    session_id = str(form.get("sessionId") or "").strip()
    is_active = str(form.get("isActive") or "1")
    settings = get_settings()
    if not _webhook_authorized(request, settings):
        return Response(status_code=403)
    if is_active not in {"1", "true", "True"}:
        return _xml(_say("Thank you. Goodbye."))
    if not caller:
        return _xml(_say("We could not identify your phone number. Please try again later."))

    try:
        supabase = await create_supabase(settings)
        repository = ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)
        patient_id = await repository.create_phone_patient(caller)
        conversation_id = await repository.create_conversation(patient_id=patient_id, channel="call")
        base = _callback_base(settings)
        # Persist the AT session ID without putting it into the clinical transcript.
        logger.info("phone conversation started", extra={"conversation_id": str(conversation_id), "session_id_present": bool(session_id)})
        consent_url = f"{base}/api/voice/consent?conversation_id={conversation_id}"
        return _xml(
            _say("Hello. I am the community health triage assistant. This call may be recorded for your healthcare team. Press 1 to consent to recording, or press 2 to be connected to a healthcare professional without recording."),
            f'<GetDigits numDigits="1" timeout="10" callbackUrl="{html.escape(consent_url, quote=True)}" finishOnKey="#"/>',
        )
    except Exception as exc:
        logger.exception("phone conversation initialization failed", extra={"error_type": type(exc).__name__})
        return _xml(_say("I am unable to start the health assessment right now. Please contact a healthcare professional."))


@router.post("/voice/consent")
async def voice_consent(request: Request) -> Response:
    form = await request.form()
    conversation_id_raw = str(form.get("conversation_id") or request.query_params.get("conversation_id") or "").strip()
    digits = str(form.get("dtmfDigits") or "").strip()
    settings = get_settings()
    if not _webhook_authorized(request, settings):
        return Response(status_code=403)
    try:
        conversation_id = UUID(conversation_id_raw)
        supabase = await create_supabase(settings)
        repository = ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)
        # Consent itself is stored as a call-recording event only when recording begins.
        consented = digits == "1"
        await repository.record_phone_consent(conversation_id=conversation_id, consented=consented)
        if consented:
            callback = f"{_callback_base(settings)}/api/voice/recording?conversation_id={conversation_id}&recording_consent=1"
            return _xml(
                _say("Thank you. Please tell me what is wrong, when it started, and how severe it is. Press hash when you finish."),
                _record(callback, max_length=settings.phone_record_max_seconds),
            )
        if settings.escalation_phone_number:
            return _xml(
                _say("Okay. I will not record this call. I will connect you to a healthcare professional now."),
                f'<Dial phoneNumbers="{html.escape(settings.escalation_phone_number, quote=True)}"/>',
            )
        return _xml(_say("Okay. I will not record this call. Please contact a healthcare professional directly for assistance."))
    except Exception as exc:
        logger.exception("phone consent handling failed", extra={"error_type": type(exc).__name__})
        return _xml(_say("I could not continue safely. Please contact a healthcare professional now."))


@router.post("/voice/recording")
async def voice_recording(request: Request) -> Response:
    """Process one AT recording and return the next XML prompt.

    This is intentionally a conservative turn-based phone path. It does not store
    raw audio itself. AT owns the recording URL; persistent call-recording storage
    is only enabled after explicit consent.
    """
    form = await request.form()
    conversation_id_raw = str(form.get("conversation_id") or request.query_params.get("conversation_id") or "").strip()
    recording_url = str(form.get("recordingUrl") or form.get("recording_url") or "").strip()
    consented = str(form.get("recording_consent") or request.query_params.get("recording_consent") or "1") != "0"
    settings = get_settings()
    if not _webhook_authorized(request, settings):
        return Response(status_code=403)
    try:
        conversation_id = UUID(conversation_id_raw)
        supabase = await create_supabase(settings)
        repository = ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)
        patient_id = await repository.conversation_patient_id(conversation_id)
        if not patient_id:
            return _xml(_say("This session has expired. Please call again."))
        if not consented:
            await repository.finish_conversation(conversation_id, status="no_recording_consent")
            return _xml(_say("I cannot process a voice recording without your consent. Please contact a healthcare professional directly."))
        if not recording_url:
            return _xml(_say("I did not receive your recording. Please try again."))

        transcript = await _transcribe_recording(recording_url, settings)
        pipeline = _build_pipeline(settings)
        previous_turn, previous_fields = await repository.load_context(conversation_id)
        context = ConversationContext(turn_number=previous_turn, fields=previous_fields)
        result = await pipeline.process_turn(transcript, context)
        await repository.save_turn(
            conversation_id=conversation_id,
            turn_number=context.turn_number,
            transcript=result.transcript,
            translated_text=result.translated_text,
            extracted_fields=result.extracted_fields.fields,
            detected_language=result.extracted_fields.detected_language,
            asr_provider="intron",
        )
        if result.state.value == "TRIAGE":
            await repository.upsert_triage_result(
                conversation_id=conversation_id,
                urgency_tier=result.urgency_tier or "AMBER",
                danger_signs=list(result.danger_phrases),
                summary=result.triage_summary or "Triage completed; clinician review required.",
            )
            await repository.finish_conversation(conversation_id, status="triage")
            if result.urgency_tier == "RED" and settings.escalation_phone_number:
                return _xml(
                    _say("This may be an emergency. I will connect you with a healthcare professional now. Please stay on the line."),
                    f'<Dial phoneNumbers="{html.escape(settings.escalation_phone_number, quote=True)}"/>',
                )
            return _xml(_say(result.response_text))
        if result.state.value == "ESCALATE":
            await repository.finish_conversation(conversation_id, status="escalated")
            return _xml(_say(result.response_text))
        callback = f"{_callback_base(settings)}/api/voice/recording?conversation_id={conversation_id}&recording_consent={'1' if consented else '0'}"
        return _xml(_say(result.response_text), _record(callback, max_length=settings.phone_record_max_seconds))
    except Exception as exc:
        logger.exception("phone recording processing failed", extra={"error_type": type(exc).__name__})
        return _xml(_say("I cannot safely continue this assessment. Please contact a healthcare professional now."))


def _build_pipeline(settings: Settings) -> ConversationPipeline:
    policy = RequiredFieldPolicy(fields=tuple(x.strip() for x in settings.required_triage_fields.split(",") if x.strip()))
    danger = DangerMatcher(tuple(x.strip() for x in settings.danger_sign_phrases.split(",") if x.strip()))
    if not settings.nvidia_api_key:
        extractor: Any = _UnavailableExtractor()
        responder: Any = SafeFallbackResponseGenerator()
    else:
        extraction_client = NvidiaClient(settings, model=settings.nvidia_extraction_model)
        response_client = NvidiaClient(settings, model=settings.nvidia_response_model)
        extractor = NvidiaExtractionProvider(extraction_client, policy.fields)
        responder = NvidiaResponseGenerator(response_client)
    return ConversationPipeline(
        extraction_provider=extractor,
        translation_provider=NllbTranslationProvider(settings),
        danger_matcher=danger,
        response_generator=responder,
        required_fields_checker=policy.is_complete,
    )


class _UnavailableExtractor:
    async def extract(self, transcript: str):
        raise RuntimeError("NVIDIA_API_KEY is not configured")


async def _transcribe_recording(url: str, settings: Settings) -> str:
    # AT records are documented as WAV/MP3. Decode/convert to PCM locally when
    # ffmpeg is present, then send compliant 1-32KB PCM chunks to Intron.
    import tempfile
    from pathlib import Path
    import subprocess
    import httpx

    async with httpx.AsyncClient(timeout=settings.external_timeout_seconds) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.content
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "recording"
        source.write_bytes(payload)
        pcm = Path(tmp) / "audio.pcm"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-f", "s16le", "-ac", "1", "-ar", str(settings.intron_stt_sample_rate), str(pcm)],
            check=True,
            capture_output=True,
            timeout=settings.external_timeout_seconds,
        )
        stream = IntronSTTStream(IntronConfig(
            endpoint=settings.intron_stt_endpoint,
            api_key=settings.intron_stt_api_key,
            sample_rate=settings.intron_stt_sample_rate,
            bit_rate=settings.intron_stt_bit_rate,
            num_channels=settings.intron_stt_channels,
            language=settings.intron_stt_language,
        ))
        await stream.connect()
        try:
            data = pcm.read_bytes()
            for offset in range(0, len(data), 16_000):
                chunk = data[offset:offset + 16_000]
                if len(chunk) < 1024:
                    break
                await stream.send_audio(chunk)
            if stream._ws is None:
                raise RuntimeError("STT stream is not connected")
            event = await stream.commit_until_final()
            text = _event_text(event)
            if not text:
                raise RuntimeError("Intron returned no committed transcript")
            return text
        finally:
            await stream.close()


def _event_text(event: dict[str, Any]) -> str:
    for key in ("transcript", "text", "partial_transcript"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""
