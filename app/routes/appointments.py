from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.integrations.conversation_repository import ConversationRepository
from app.models.api_models import (
    AppointmentListResponse,
    ErrorResponse,
    RouteAppointmentResponse,
)
from app.routes.deps import get_repository, require_patient_id
from app.scheduling import route_appointment

router = APIRouter(tags=["appointments"])


class RouteAppointmentRequest(BaseModel):
    conversation_id: UUID


@router.get(
    "/appointments",
    response_model=AppointmentListResponse,
    responses={401: {"model": ErrorResponse}},
    summary="List my appointments",
)
async def list_my_appointments(
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Patient-facing: their own appointment dates, most recent first."""
    appointments = await repository.appointments_for_patient(patient_id)
    return {"appointments": appointments}


@router.post(
    "/appointments/route",
    response_model=RouteAppointmentResponse,
    status_code=201,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Auto-book earliest free doctor slot",
)
async def route_my_appointment(
    body: RouteAppointmentRequest,
    patient_id=Depends(require_patient_id),
    repository: ConversationRepository = Depends(get_repository),
) -> dict:
    """Book the earliest free doctor slot for a triaged conversation.

    Called by the web-voice client after TRIAGE_UPDATE; the phone channel
    calls the same function internally in voice_webhook.py.
    """
    triage = await repository.triage_for_conversation(body.conversation_id)
    if not triage:
        raise HTTPException(status_code=404, detail="No triage result for this conversation yet")
    owner = await repository.conversation_patient_id(body.conversation_id)
    if owner != patient_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    try:
        appointment = await route_appointment(
            repository,
            patient_id=patient_id,
            conversation_id=body.conversation_id,
            tier=str(triage.get("urgency_tier") or "AMBER"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"appointment": appointment}
