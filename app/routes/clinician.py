from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.integrations.conversation_repository import ConversationRepository
from app.routes.deps import get_repository, require_clinician_id

router = APIRouter(tags=["clinician"])


@router.get("/clinician/queue")
async def get_appointment_queue(
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Clinician-facing: pending/upcoming appointments, most urgent first
    (RED > AMBER > GREEN, matching the pipeline's urgency_tier)."""
    appointments = await repository.appointment_queue_for_clinician(doctor_id)
    return {"appointments": appointments}


@router.get("/clinician/patients/{patient_id}/triage-form")
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
