from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.core.lifespan import lifespan
from app.websocket.router import router as websocket_router
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(websocket_router)


@app.get('/metrics')
async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)