from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.app_state import AppState
from app.core.logging import configure_logging, logger
from app.infrastructure.database.session import (
    create_session_factory,
    dispose_engine,
)

from app.infrastructure.redis.client import create_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""

    configure_logging()

    logger.info("application_starting")

    redis = create_redis_client()
    session_factory = create_session_factory()

    app.state.resources = AppState(
        redis=redis,
        session_factory=session_factory,
    )
    app.state.startup_time = time.time()

    logger.info("application_started")

    try:
        yield
    finally:
        logger.info("application_stopping")

        await redis.aclose()
        await dispose_engine()

        logger.info("application_stopped")