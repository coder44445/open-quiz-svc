from __future__ import annotations

from typing import Any

from redis.asyncio import Redis

from app.core.config import settings

redis = Redis.from_url(settings.redis_url, decode_responses=True)

async def enqueue_job(func_name: str, *args: Any) -> Any:
    from arq.connections import create_pool, RedisSettings

    pool = await create_pool(RedisSettings.from_url(settings.redis_url))
    try:
        return await pool.enqueue_job(func_name, *args)
    finally:
        await pool.close()
