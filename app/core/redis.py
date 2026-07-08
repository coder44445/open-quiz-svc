from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from redis.asyncio import Redis
from arq.connections import create_pool, RedisSettings

from app.core.config import settings
from app.core.logging import logger

# Shared Redis client used for pub/sub and idempotency keys.
# Individual services that need their own connection should use
# create_redis_client() from app.infrastructure.redis.client.
redis = Redis.from_url(settings.redis_url, decode_responses=True)


def get_arq_settings(url: str) -> RedisSettings:
    """Parse a Redis URL and return ARQ-compatible connection settings.

    ARQ does not accept a raw URL, so we extract host, port, database, and
    password from the parsed URL and build a RedisSettings object.
    """

    parsed = urlparse(url)

    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def enqueue_job(func_name: str, *args: Any) -> Any:
    """Enqueue a background job via ARQ.

    Creates a short-lived connection pool, enqueues the job, then
    closes the pool.  Callers should not cache the pool themselves
    because ARQ pools are not safe to share across async contexts.

    Args:
        func_name: Registered ARQ worker function name.
        *args:     Positional arguments forwarded to the function.

    Returns:
        The ARQ job handle, or None if enqueuing failed.
    """

    arq_settings = get_arq_settings(settings.redis_url)
    logger.debug("job_enqueueing", func_name=func_name)

    pool = await create_pool(arq_settings)
    try:
        job = await pool.enqueue_job(func_name, *args)
        logger.info("job_enqueued", func_name=func_name, job_id=getattr(job, "job_id", None))
        return job
    except Exception:
        logger.exception("job_enqueue_failed", func_name=func_name)
        raise
    finally:
        await pool.close()
