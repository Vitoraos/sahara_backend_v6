from __future__ import annotations

from fastapi import APIRouter, Depends

from app.integrations.conversation_repository import ConversationRepository
from app.models.api_models import ErrorResponse, HistoryResponse
from app.routes.deps import get_repository, require_patient_id

router = APIRouter(tags=["history"])


@router.get(
    "/history",
    response_model=HistoryResponse,
    responses={401: {"model": ErrorResponse}},
    summary="My conversation history with triage outcomes",
)
async def list_my_conversation_history(
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Patient-facing: past triage conversations with the agent, each with
    its triage outcome (if one was reached)."""
    conversations = await repository.conversation_history_for_patient(patient_id)
    return {"conversations": conversations}
