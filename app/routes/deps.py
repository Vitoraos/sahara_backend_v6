from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.integrations.conversation_repository import ConversationRepository
from app.integrations.redis_client import RedisClient
from app.integrations.supabase_client import SupabaseClient, get_supabase

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, description="Supabase session JWT")

AUTH_CACHE_TTL_SECONDS = 60


async def get_repository(
    supabase: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
) -> ConversationRepository:
    return ConversationRepository(supabase, timeout_seconds=settings.persistence_timeout_seconds)


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return credentials.credentials.strip()


async def _cached_profile(repository, settings, *, token: str, kind: str, lookup):
    """Token → profile-row cache. Misses and Redis failures fall through to
    the live lookup so auth never depends on Redis availability.

    # ponytail: 60s revocation delay on deactivation; drop the TTL when
    # instant revocation matters.
    """
    key = f"sahara:auth:{kind}:" + hashlib.sha256(token.encode()).hexdigest()
    if settings is not None and settings.redis_url:
        try:
            client = RedisClient(settings).client
            cached = await client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning("auth cache read failed", extra={"error_type": type(exc).__name__})
            client = None
        else:
            row = await lookup(token)
            if row is not None:
                try:
                    await client.setex(key, AUTH_CACHE_TTL_SECONDS, json.dumps({"id": str(row["id"])}))
                except Exception as exc:
                    logger.warning("auth cache write failed", extra={"error_type": type(exc).__name__})
            return row
    return await lookup(token)


async def require_patient_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> UUID:
    """Resolves the caller's patient identity from their Supabase session
    token. This check is the real access boundary for these routes: the
    backend uses the Supabase service-role key, which bypasses RLS, so
    RLS alone does not protect these endpoints — this dependency does.
    """
    token = _bearer_token(credentials)
    row = await _cached_profile(
        repository, settings=settings, token=token, kind="patient",
        lookup=repository.patient_for_access_token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Not a recognized patient session")
    return UUID(str(row["id"]))


async def require_clinician_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    repository: ConversationRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> UUID:
    token = _bearer_token(credentials)
    row = await _cached_profile(
        repository, settings=settings, token=token, kind="clinician",
        lookup=repository.clinician_for_access_token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Not a recognized clinician session")
    return UUID(str(row["id"]))
