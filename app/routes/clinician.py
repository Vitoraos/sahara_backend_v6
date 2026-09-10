from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.integrations.conversation_repository import ConversationRepository
from app.models.api_models import (
    AvailabilityResponse,
    ErrorResponse,
    QueueResponse,
    TriageFormResponse,
)
from app.routes.deps import get_repository, require_clinician_id

router = APIRouter(tags=["clinician"])


class AvailabilityWindow(BaseModel):
    weekday: int
    start: str
    end: str


class AvailabilityUpdate(BaseModel):
    windows: list[AvailabilityWindow]


@router.get(
    "/clinician/availability",
    response_model=AvailabilityResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Get my weekly availability",
)
async def get_my_availability(
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Doctor's own weekly windows (UTC, HH:MM)."""
    return {"windows": await repository.availability_for_doctor(doctor_id)}


@router.put(
    "/clinician/availability",
    response_model=AvailabilityResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    summary="Replace my weekly availability",
)
async def set_my_availability(
    body: AvailabilityUpdate,
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Replace all weekly windows. A weekday with no window means unavailable."""
    windows: list[dict] = []
    for window in body.windows:
        if not 0 <= window.weekday <= 6:
            raise HTTPException(status_code=422, detail="weekday must be 0 (Monday) to 6 (Sunday)")
        for label in ("start", "end"):
            value = getattr(window, label)
            try:
                hour, minute = (int(part) for part in value.split(":"))
                assert 0 <= hour < 24 and 0 <= minute < 60
            except (ValueError, AssertionError):
                raise HTTPException(status_code=422, detail=f"{label} must be HH:MM, got {value!r}")
        if window.start >= window.end:
            raise HTTPException(status_code=422, detail="start must be before end")
        windows.append({"weekday": window.weekday, "start_time": window.start, "end_time": window.end})
    return {"windows": await repository.replace_availability(doctor_id=doctor_id, windows=windows)}


@router.get(
    "/clinician/queue",
    response_model=QueueResponse,
    responses={401: {"model": ErrorResponse}},
    summary="My appointment queue with triage reports",
)
async def get_appointment_queue(
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Clinician-facing: pending/upcoming appointments, most urgent first
    (RED > AMBER > GREEN, matching the pipeline's urgency_tier), each with
    the patient details and the voice-agent triage report embedded."""
    appointments = await repository.appointment_queue_for_clinician(doctor_id)
    enriched = []
    for appointment in appointments:
        # ponytail: N+1 reads are fine at queue scale; single join when slow.
        patient = await repository.patient_by_id(UUID(str(appointment["patient_id"])))
        triage_report = (
            await repository.triage_form_for_patient(UUID(str(appointment["patient_id"])))
        )
        enriched.append(
            {
                **appointment,
                "patient": (
                    {
                        "name": patient.get("name"),
                        "phone_number": patient.get("phone_number"),
                        "email": patient.get("email"),
                    }
                    if patient
                    else None
                ),
                "triage_report": triage_report,
            }
        )
    return {"appointments": enriched}


@router.get(
    "/clinician/patients/{patient_id}/triage-form",
    response_model=TriageFormResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="Triage report for one assigned patient",
)
async def get_patient_triage_form(
    patient_id: UUID,
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Clinician-facing: the structured fields, danger signs, and summary
    captured for one patient's triage conversation. Access is scoped to
    patients this clinician has an appointment with — matching the RLS
    policy shape exactly, not just the active queue."""
    assigned = await repository.patient_assigned_to_clinician(
        patient_id=patient_id, doctor_id=doctor_id
    )
    if not assigned:
        raise HTTPException(status_code=404, detail="Patient not found in your queue")
    form = await repository.triage_form_for_patient(patient_id)
    if not form:
        raise HTTPException(status_code=404, detail="No triage record found for this patient")
    return form
