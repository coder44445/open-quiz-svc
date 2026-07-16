from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, Response

from app.api.health import router as health_router
from app.api.game import router as game_router
from app.api.matches import router as matches_router
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging import logger
from app.websocket.router import router as websocket_router
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response as FastAPIResponse


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(game_router)
app.include_router(matches_router)
app.include_router(websocket_router)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    """Log every HTTP request with method, path, status code and latency.

    A unique request_id is generated per request and attached to the log so
    individual requests can be traced across log lines.  WebSocket upgrade
    requests (handled by the /ws route) are intentionally still logged here
    so connection attempts are visible.
    """

    request_id = str(uuid.uuid4())
    start = time.perf_counter()

    logger.info(
        "http_request_started",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else "unknown",
    )

    try:
        response: Response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.exception(
            "http_request_error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            elapsed_ms=elapsed_ms,
        )
        raise

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(
        "http_request_finished",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
    )

    return response


@app.get("/metrics")
async def metrics_endpoint() -> FastAPIResponse:
    """Expose Prometheus metrics for scraping."""
    data = generate_latest()
    return FastAPIResponse(content=data, media_type=CONTENT_TYPE_LATEST)