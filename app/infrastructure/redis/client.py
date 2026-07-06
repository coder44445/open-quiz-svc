from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings


def create_redis_client() -> Redis:
    """Create a Redis client."""

    return Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )