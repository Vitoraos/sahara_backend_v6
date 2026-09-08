from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Patient(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    phone_number: str
    name: str | None = None
    auth_user_id: UUID | None = None
    created_at: datetime


class Clinician(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    phone_number: str
    auth_user_id: UUID
    created_at: datetime


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    patient_id: UUID
    channel: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str


class Turn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    turn_number: int
    transcript: str
    translated_text: str | None = None
    extracted_fields: dict[str, Any]
    detected_language: dict[str, Any]
    asr_provider: str
    created_at: datetime


class TriageResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    urgency_tier: str
    danger_signs: list[str]
    summary: str
    created_at: datetime


class Appointment(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    patient_id: UUID
    conversation_id: UUID | None = None
    tier: str
    scheduled_at: datetime
    doctor_id: UUID | None = None
    status: str
    notified_via: str | None = None


class Prescription(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    medication: str
    dosage: str
    instructions: str
    issued_at: datetime
    status: str


class CallRecording(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    appointment_id: UUID
    consent_recorded_at: datetime
    recording_url: str | None = None
    transcript: str | None = None
    key_points_summary: str | None = None
    created_at: datetime


class BenchmarkRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    model_name: str
    language_pair: str
    wer: float
    entity_accuracy: float
    run_at: datetime
