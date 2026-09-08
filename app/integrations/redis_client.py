from collections.abc import AsyncIterator

from fastapi import Depends

from app.config import Settings, get_settings


class RedisClient:
    def __init__(self, settings: Settings) -> None:
        self.url = settings.redis_url


async def get_redis(settings: Settings = Depends(get_settings)) -> AsyncIterator[RedisClient]:
    client = RedisClient(settings)
    yield client
