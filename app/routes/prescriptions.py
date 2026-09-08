from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.integrations.conversation_repository import ConversationRepository
from app.routes.deps import get_repository, require_clinician_id, require_patient_id

router = APIRouter(tags=["prescriptions"])


class PrescriptionCreateRequest(BaseModel):
    patient_id: UUID
    medication: str = Field(min_length=1)
    dosage: str = Field(min_length=1)
    instructions: str = Field(min_length=1)


@router.get("/prescriptions")
async def list_my_prescriptions(
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Patient-facing prescription inbox."""
    prescriptions = await repository.prescriptions_for_patient(patient_id)
    return {"prescriptions": prescriptions}


@router.post("/prescriptions", status_code=201)
async def create_prescription(
    body: PrescriptionCreateRequest,
    doctor_id=Depends(require_clinician_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Clinician-facing: send a prescription to a patient."""
    prescription = await repository.create_prescription(
        patient_id=body.patient_id,
        doctor_id=doctor_id,
        medication=body.medication,
        dosage=body.dosage,
        instructions=body.instructions,
    )
    return {"prescription": prescription}
