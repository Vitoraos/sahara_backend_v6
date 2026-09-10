import redis.asyncio as aioredis
from collections.abc import AsyncIterator

from fastapi import Depends

from app.config import Settings, get_settings


class RedisClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is not configured")
        self.url = settings.redis_url

    @property
    def client(self) -> aioredis.Redis:
        # ponytail: single shared connection per process; pool when
        # concurrent voice sessions saturate it.
        global _shared
        if _shared is None:
            _shared = aioredis.from_url(self.url, decode_responses=True)
        return _shared


_shared: aioredis.Redis | None = None


async def get_redis(settings: Settings = Depends(get_settings)) -> AsyncIterator[RedisClient]:
    client = RedisClient(settings)
    yield client