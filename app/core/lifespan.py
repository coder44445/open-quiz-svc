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
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown.

    Initialises shared resources (Redis, database session factory) during
    startup and tears them down cleanly on shutdown.  Any exception during
    startup propagates immediately so the process exits non-zero rather than
    silently serving broken requests.
    """

    configure_logging()

    logger.info(
        "application_starting",
        environment=settings.environment,
        debug=settings.debug,
    )

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

        try:
            await redis.aclose()
            logger.info("redis_connection_closed")
        except Exception:
            logger.exception("redis_close_error")

        try:
            await dispose_engine()
            logger.info("database_engine_disposed")
        except Exception:
            logger.exception("database_dispose_error")

        logger.info("application_stopped")