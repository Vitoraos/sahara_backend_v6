from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import acreate_client

from app.config import Settings, get_settings
from app.integrations.conversation_repository import ConversationRepository
from app.models.api_models import DoctorSignupResponse, ErrorResponse, PatientSignupResponse
from app.routes.deps import get_repository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


class PatientSignup(BaseModel):
    name: str
    phone_number: str
    email: str
    password: str


class DoctorSignup(BaseModel):
    name: str
    phone_number: str
    email: str
    password: str
    license_number: str
    specialty: str
    confirm_license: bool


@router.post(
    "/auth/patient/signup",
    response_model=PatientSignupResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Sign up as a patient",
)
async def patient_signup(
    body: PatientSignup,
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_id, access_token = await _sign_up_user(settings, email=body.email.strip(), password=body.password)
    try:
        row = await repository.create_patient_profile(
            name=body.name.strip(),
            phone_number=body.phone_number.strip(),
            email=body.email.strip(),
            auth_user_id=user_id,
        )
    except Exception as exc:
        raise _conflict_or_raise(exc)
    return {"patient_id": row["id"], "access_token": access_token}


@router.post(
    "/auth/doctor/signup",
    response_model=DoctorSignupResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="Sign up as a doctor (dummy license verify)",
)
async def doctor_signup(
    body: DoctorSignup,
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    # ponytail: dummy verify — any non-empty license/specialty plus the
    # checkbox is accepted and stored as-is; check a real medical register
    # before production.
    if not body.confirm_license:
        raise HTTPException(status_code=422, detail="Please confirm you are a licensed doctor")
    if not body.license_number.strip() or not body.specialty.strip():
        raise HTTPException(status_code=422, detail="License number and specialty are required")
    user_id, access_token = await _sign_up_user(settings, email=body.email.strip(), password=body.password)
    try:
        row = await repository.create_clinician_profile(
            name=body.name.strip(),
            phone_number=body.phone_number.strip(),
            email=body.email.strip(),
            auth_user_id=user_id,
            license_number=body.license_number.strip(),
            specialty=body.specialty.strip(),
        )
    except Exception as exc:
        raise _conflict_or_raise(exc)
    return {"doctor_id": row["id"], "access_token": access_token}


async def _sign_up_user(settings: Settings, *, email: str, password: str) -> tuple[UUID, str | None]:
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="SUPABASE_URL and SUPABASE_ANON_KEY are required for signup")
    client = await acreate_client(settings.supabase_url, settings.supabase_anon_key)
    try:
        response = await client.auth.sign_up({"email": email, "password": password})
    except Exception as exc:
        logger.warning("supabase signup failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=400, detail="Signup failed: email may already be registered or password too short")
    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None) if user else None
    if not user_id:
        raise HTTPException(status_code=400, detail="Signup failed: email may already be registered")
    session = getattr(response, "session", None)
    # access_token is None when "Confirm email" is enabled in Supabase Auth:
    # the profile row already exists, so the user signs in client-side after
    # confirming.
    access_token = getattr(session, "access_token", None) if session else None
    return UUID(str(user_id)), access_token


def _conflict_or_raise(exc: Exception) -> HTTPException:
    message = str(exc).lower()
    if "23505" in message or "duplicate" in message or "unique" in message:
        return HTTPException(status_code=409, detail="Phone number or email is already registered")
    logger.exception("profile creation failed", extra={"error_type": type(exc).__name__})
    return HTTPException(status_code=500, detail="Could not create profile")
