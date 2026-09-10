from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.db_models import Prescription


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Not a recognized patient session"])


class PatientSignupResponse(BaseModel):
    patient_id: UUID
    access_token: str | None = Field(
        default=None,
        description="Supabase session JWT. Null when 'Confirm email' is enabled until the user confirms.",
    )


class DoctorSignupResponse(BaseModel):
    doctor_id: UUID
    access_token: str | None = Field(default=None, description="Supabase session JWT. Null until email confirmed.")


class AvailabilityWindowOut(BaseModel):
    id: UUID | None = None
    doctor_id: UUID | None = None
    weekday: int = Field(examples=[1], description="0=Monday..6=Sunday (UTC)")
    start_time: str = Field(examples=["09:00:00"])
    end_time: str = Field(examples=["12:00:00"])


class AvailabilityResponse(BaseModel):
    windows: list[AvailabilityWindowOut]


class AppointmentOut(BaseModel):
    id: UUID
    patient_id: UUID
    conversation_id: UUID | None = None
    tier: str = Field(examples=["AMBER"])
    scheduled_at: datetime
    doctor_id: UUID | None = None
    status: str = Field(examples=["scheduled"])
    notified_via: str | None = None


class AppointmentListResponse(BaseModel):
    appointments: list[AppointmentOut]


class RouteAppointmentResponse(BaseModel):
    appointment: AppointmentOut


class QueuePatient(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    email: str | None = None


class QueueItemOut(AppointmentOut):
    patient: QueuePatient | None = None
    triage_report: dict[str, Any] | None = Field(
        default=None,
        description="Voice-agent triage report: conversation_id, fields, and triage_result.",
    )


class QueueResponse(BaseModel):
    appointments: list[QueueItemOut]


class TriageFormResponse(BaseModel):
    conversation_id: UUID
    conversation_started_at: datetime | None = None
    fields: dict[str, Any] = Field(examples=[{"chief_complaint": "fever", "symptom_onset": "today"}])
    triage_result: dict[str, Any] | None = None


class ConversationHistoryItem(BaseModel):
    id: UUID
    channel: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None
    triage_result: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    conversations: list[ConversationHistoryItem]


class PrescriptionListResponse(BaseModel):
    prescriptions: list[Prescription]


class PrescriptionCreateResponse(BaseModel):
    prescription: Prescription


class ClickToCallResponse(BaseModel):
    session_id: str
    call_recording: dict[str, Any] | None = None


class PatientJoinResponse(BaseModel):
    session_id: str


class CallSummaryResponse(BaseModel):
    key_points_summary: str
