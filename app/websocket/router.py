from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pydantic import ValidationError

from app.core.logging import logger
from app.websocket.event_gateway import EventGateway
from app.websocket.schemas import (
    ClientEventAdapter, JoinEvent, TopicEvent, StartEvent, 
    BeginEvent, AnswerEvent, RejoinEvent
)
from app.websocket.handlers import ConnectionContext, WebSocketEventHandlers

router = APIRouter()
event_gateway = EventGateway()


@router.websocket("/ws/{room_id}")
async def websocket_room(websocket: WebSocket, room_id: str) -> None:
    """Handle all WebSocket traffic for a single quiz room.

    Each connected client sends JSON messages with a ``type`` field that acts
    as a command discriminator.  Supported types:

    - ``join``   — register the player and receive a player_id
    - ``topic``  — submit a quiz topic
    - ``start``  — trigger AI question generation (transitions LOBBY → GENERATING)
    - ``begin``  — start the timed game loop (transitions READY → IN_PROGRESS)
    - ``answer`` — submit an answer for the current question
    - ``rejoin`` — sync state for a reconnecting client

    The game loop is intentionally started as an asyncio background task so
    this WebSocket can keep receiving messages (answers, rejoins, disconnects)
    while questions are ticking.  Unknown event types are logged and ignored.
    """

    await websocket.accept()

    # Subscribe this client to room-level Redis Pub/Sub events in the background.
    asyncio.create_task(event_gateway.subscribe(room_id, websocket))

    # Create connection context
    ctx = ConnectionContext(room_id=room_id, websocket=websocket)
    ctx.log.info("websocket_client_connected")

    try:
        while True:
            # We receive raw text/bytes so we can parse with Pydantic
            raw_data = await websocket.receive_text()

            try:
                # TypeAdapter.validate_json automatically discriminates by the "type" field
                payload = ClientEventAdapter.validate_json(raw_data)
            except ValidationError as exc:
                ctx.log.warning("websocket_invalid_payload", error=str(exc))
                continue
                
            ctx.log.debug("websocket_event_received", event_type=payload.type, player_id=ctx.player_id)

            # Dispatch to appropriate handler
            if isinstance(payload, JoinEvent):
                await WebSocketEventHandlers.handle_join(ctx, payload)
            elif isinstance(payload, TopicEvent):
                await WebSocketEventHandlers.handle_topic(ctx, payload)
            elif isinstance(payload, StartEvent):
                await WebSocketEventHandlers.handle_start(ctx, payload)
            elif isinstance(payload, BeginEvent):
                await WebSocketEventHandlers.handle_begin(ctx, payload)
            elif isinstance(payload, AnswerEvent):
                await WebSocketEventHandlers.handle_answer(ctx, payload)
            elif isinstance(payload, RejoinEvent):
                await WebSocketEventHandlers.handle_rejoin(ctx, payload)
            else:
                ctx.log.warning("websocket_unhandled_event", payload_type=type(payload).__name__)

    except WebSocketDisconnect:
        ctx.log.info("websocket_client_disconnected")
        # Cancel the loop task if the host disconnects mid-game.
        if ctx.loop_task and not ctx.loop_task.done():
            ctx.loop_task.cancel()
            ctx.log.info("game_loop_cancelled_on_disconnect")

    except Exception:
        ctx.log.exception("websocket_unhandled_error")
