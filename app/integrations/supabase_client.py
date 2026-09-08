from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import Depends
from supabase import AsyncClient, acreate_client

from app.config import Settings, get_settings


class SupabaseClient:
    """Server-side async Supabase boundary.

    The service/secret key is used only by the backend for persistence. RLS remains
    enabled for user-facing Data API access; this client is never exposed to a user.
    """

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def close(self) -> None:
        # supabase-py owns its underlying HTTP clients; there is no stable public
        # close API across supported versions, so this is intentionally a no-op.
        return None


_client: SupabaseClient | None = None


async def get_supabase(settings: Settings = Depends(get_settings)) -> AsyncIterator[SupabaseClient]:
    global _client
    if _client is None:
        key = settings.supabase_service_role_key
        if not settings.supabase_url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server persistence")
        _client = SupabaseClient(await acreate_client(settings.supabase_url, key))
    yield _client


async def create_supabase(settings: Settings) -> SupabaseClient:
    global _client
    if _client is None:
        key = settings.supabase_service_role_key
        if not settings.supabase_url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server persistence")
        _client = SupabaseClient(await acreate_client(settings.supabase_url, key))
    return _client
