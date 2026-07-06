from __future__ import annotations

import time
import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

router = APIRouter(tags=["Health"])


def _get_resources(request: Request):
    """
    Fetch shared application resources from FastAPI app state.

    Expected structure:
        request.app.state.resources = {
            redis: Redis client
            session_factory: async DB session factory
        }

    Returns None if resources are not initialized.
    """
    return getattr(request.app.state, "resources", None)


async def _check_redis(redis) -> bool:
    """
    Check Redis availability with timeout protection.
    Returns True if Redis responds to ping, otherwise False.
    """
    try:
        return await asyncio.wait_for(redis.ping(), timeout=1.5)
    except Exception:
        return False


async def _check_db(session_factory) -> bool:
    """
    Check database connectivity by executing a lightweight query.

    Uses a short timeout to avoid hanging readiness probes.
    """
    try:
        async with session_factory() as session:
            await asyncio.wait_for(
                session.execute(text("SELECT 1")),
                timeout=2.0
            )
        return True
    except Exception:
        return False


@router.get("/livez")
async def livez() -> dict[str, str]:
    """
    Liveness probe.

    Only verifies that the application process is running.
    Must NOT depend on external systems like DB or Redis.
    """
    return {"status": "alive"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """
    Readiness probe.

    Determines whether the service is ready to accept traffic.
    Checks critical dependencies like DB and Redis.
    """

    resources = _get_resources(request)

    # If resources are not initialized, service is not ready
    if resources is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="resources not initialized",
        )

    # Run dependency checks in parallel for faster response
    db_ok, redis_ok = await asyncio.gather(
        _check_db(resources.session_factory),
        _check_redis(resources.redis),
    )

    # If any critical dependency is down, reject traffic
    if not (db_ok and redis_ok):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "db": db_ok,
                "redis": redis_ok,
            },
        )

    return {"status": "ready"}


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    """
    Health endpoint.

    Provides diagnostic information about the application state.
    Unlike readiness, this is for monitoring/observability only.
    """

    resources = _get_resources(request)

    db_ok = False
    redis_ok = False

    # If resources exist, perform dependency checks
    if resources:
        db_ok, redis_ok = await asyncio.gather(
            _check_db(resources.session_factory),
            _check_redis(resources.redis),
        )

    # Calculate uptime if startup time is available
    startup_time = getattr(request.app.state, "startup_time", None)
    uptime = int(time.time() - startup_time) if startup_time else None

    # Overall system status
    status_value = "ok" if (db_ok and redis_ok) else "degraded"

    return {
        "status": status_value,
        "db": db_ok,
        "redis": redis_ok,
        "uptime_seconds": uptime,
    }