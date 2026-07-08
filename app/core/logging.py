from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings


# Noisy third-party loggers that clutter output without adding value.
_SUPPRESSED_LOGGERS = (
    "uvicorn.access",       # per-request HTTP lines already handled by middleware
    "sqlalchemy.engine",    # raw SQL; exposed only when settings.debug is True
    "httpcore",             # low-level HTTP internals used by ollama client
    "httpx",                # same as httpcore
)


def configure_logging() -> None:
    """Configure application-wide logging.

    Development  → human-readable key=value output, DEBUG level.
    Production   → JSON output, INFO level, ready for log aggregators.

    All stdlib loggers (uvicorn, sqlalchemy, etc.) are bridged into
    structlog so a single pipeline controls every log line.
    """

    log_level = logging.DEBUG if settings.debug else logging.INFO

    # Shared processors that run before the final renderer.
    # Note: add_logger_name is omitted because it requires a stdlib-backed
    # logger; our PrintLoggerFactory does not provide a .name attribute.
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="timestamp", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.EventRenamer("event"),
    ]

    if settings.environment == "production":
        # Structured JSON — parseable by Datadog, CloudWatch, Loki, etc.
        renderer = structlog.processors.JSONRenderer()
    else:
        # Coloured, human-readable output for local development.
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            # Render exceptions inline so both renderers receive a string.
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging into structlog so uvicorn, sqlalchemy, arq, etc.
    # all flow through the same pipeline and formatting.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    # Suppress known noisy loggers to reduce noise in non-debug environments.
    for name in _SUPPRESSED_LOGGERS:
        suppress_level = logging.DEBUG if settings.debug else logging.WARNING
        logging.getLogger(name).setLevel(suppress_level)

    # SQLAlchemy statement echoing is controlled by the engine's echo flag,
    # but we still cap the logger level here for safety.
    if not settings.debug:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# Module-level convenience logger; import and use from any module.
logger = structlog.get_logger(__name__)