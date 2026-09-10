from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.calls.call_recorder import CallRecorder, ConsentRequiredError
from app.calls.call_summary import CallSummaryService
from app.calls.click_to_call import ClickToCallService
from app.config import Settings, get_settings
from app.dialogue.llm_provider import OpenRouterClient
from app.integrations.conversation_repository import ConversationRepository
from app.models.api_models import (
    CallSummaryResponse,
    ClickToCallResponse,
    ErrorResponse,
    PatientJoinResponse,
)
from app.routes.deps import get_repository, require_clinician_id, require_patient_id

router = APIRouter(tags=["calls"])


class ClickToCallRequest(BaseModel):
    appointment_id: UUID
    patient_phone_number: str
    consent_confirmed: bool


class SummarizeCallRequest(BaseModel):
    transcript: str


@router.post(
    "/calls/click-to-call",
    response_model=ClickToCallResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Doctor bridges a call for an appointment",
)
async def click_to_call(
    body: ClickToCallRequest,
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Clinician-facing call button: bridges the clinic's calling number
    and the patient's number for a specific appointment.

    Recording only starts if consent_confirmed is explicitly true — per
    RULES.md rule 4, never record silently.
    """
    appointment = await repository.appointment_by_id(body.appointment_id)
    if not appointment or str(appointment.get("doctor_id")) != str(doctor_id):
        raise HTTPException(status_code=404, detail="Appointment not found in your queue")
    if not settings.escalation_phone_number:
        raise HTTPException(status_code=503, detail="Clinic calling number is not configured")

    call_service = ClickToCallService(settings)
    session_id = await call_service.bridge(
        settings.escalation_phone_number, body.patient_phone_number
    )

    call_recording = None
    if body.consent_confirmed:
        recorder = CallRecorder(repository)
        try:
            call_recording = await recorder.start(
                appointment_id=body.appointment_id, consent_recorded=True
            )
        except ConsentRequiredError:  # pragma: no cover - guarded by the `if` above
            pass
    return {"session_id": session_id, "call_recording": call_recording}


@router.post(
    "/calls/patient-join/{appointment_id}",
    response_model=PatientJoinResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Patient joins their appointment call",
)
async def patient_join_call(
    appointment_id: UUID,
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Patient-facing call button: dials the patient's own on-file number
    to connect them into their appointment call."""
    appointment = await repository.appointment_by_id(appointment_id)
    if not appointment or str(appointment.get("patient_id")) != str(patient_id):
        raise HTTPException(status_code=404, detail="Appointment not found")
    patient = await repository.patient_by_id(patient_id)
    if not patient or not patient.get("phone_number"):
        raise HTTPException(status_code=400, detail="No phone number on file")
    if not settings.escalation_phone_number:
        raise HTTPException(status_code=503, detail="Calling number is not configured")

    call_service = ClickToCallService(settings)
    session_id = await call_service.bridge(
        settings.escalation_phone_number, patient["phone_number"]
    )
    return {"session_id": session_id}


@router.post(
    "/calls/{call_recording_id}/summarize",
    response_model=CallSummaryResponse,
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Summarize a call transcript for the record",
)
async def summarize_call(
    call_recording_id: UUID,
    body: SummarizeCallRequest,
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Stores an LLM-extracted key-points summary of a call transcript for
    the doctor's record.

    NOTE: this takes the transcript as input rather than transcribing a
    recording itself. Sahara's file-upload STT endpoint (needed to
    transcribe a completed call recording after the fact) is still
    unconfirmed against real docs — wire that in ahead of this once
    confirmed, rather than assuming a schema for it here.
    """
    if not settings.openrouter_api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not configured")
    client = OpenRouterClient(settings, model=settings.openrouter_summary_model)
    summary_service = CallSummaryService(client)
    summary = await summary_service.summarize(body.transcript)
    await repository.update_call_recording(
        call_recording_id=call_recording_id,
        transcript=body.transcript,
        key_points_summary=summary,
    )
    return {"key_points_summary": summary}
