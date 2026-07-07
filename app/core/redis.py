from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from redis.asyncio import Redis
from arq.connections import create_pool, RedisSettings

from app.core.config import settings

redis = Redis.from_url(settings.redis_url, decode_responses=True)


def get_arq_settings(url: str) -> RedisSettings:
    
    parsed = urlparse(url)

    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )

async def enqueue_job(func_name: str, *args: Any) -> Any:

    pool = await create_pool(get_arq_settings(settings.redis_url))
    try:
        return await pool.enqueue_job(func_name, *args)
    finally:
        await pool.close()
