from __future__ import annotations

from fastapi import APIRouter, Depends

from app.integrations.conversation_repository import ConversationRepository
from app.routes.deps import get_repository, require_patient_id

router = APIRouter(tags=["appointments"])


@router.get("/appointments")
async def list_my_appointments(
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Patient-facing: their own appointment dates, most recent first."""
    appointments = await repository.appointments_for_patient(patient_id)
    return {"appointments": appointments}
