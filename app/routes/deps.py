from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.integrations.conversation_repository import ConversationRepository
from app.integrations.supabase_client import SupabaseClient, get_supabase


async def get_repository(
    supabase: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
) -> ConversationRepository:
    return ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


async def require_patient_id(
    authorization: str | None = Header(default=None),
    repository: ConversationRepository = Depends(get_repository),
) -> UUID:
    """Resolves the caller's patient identity from their Supabase session
    token. This check is the real access boundary for these routes: the
    backend uses the Supabase service-role key, which bypasses RLS, so
    RLS alone does not protect these endpoints — this dependency does.
    """
    token = _bearer_token(authorization)
    row = await repository.patient_for_access_token(token)
    if not row:
        raise HTTPException(status_code=401, detail="Not a recognized patient session")
    return UUID(str(row["id"]))


async def require_clinician_id(
    authorization: str | None = Header(default=None),
    repository: ConversationRepository = Depends(get_repository),
) -> UUID:
    token = _bearer_token(authorization)
    row = await repository.clinician_for_access_token(token)
    if not row:
        raise HTTPException(status_code=401, detail="Not a recognized clinician session")
    return UUID(str(row["id"]))
