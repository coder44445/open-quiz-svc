from __future__ import annotations

import asyncio
import json

import structlog

from fastapi import WebSocket

from app.core.redis import redis

logger = structlog.get_logger(__name__)


class EventGateway:
    """Listens to Redis Pub/Sub and forwards events to WebSocket clients.

    Maintains exactly ONE Redis Pub/Sub subscription per room, regardless of
    how many WebSocket clients are connected to that room. When a message is
    received from Redis, it fans out (broadcasts) to all active WebSockets.
    """

    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    async def add_connection(self, room_id: str, websocket: WebSocket) -> None:
        """Register a WebSocket and start the room's Redis listener if needed."""
        if room_id not in self.connections:
            self.connections[room_id] = set()
            self.tasks[room_id] = asyncio.create_task(self._listen_to_room(room_id))
            
        self.connections[room_id].add(websocket)
        logger.info("websocket_added_to_gateway", room_id=room_id, count=len(self.connections[room_id]))

    async def remove_connection(self, room_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket and cancel the Redis listener if room is empty."""
        if room_id in self.connections:
            self.connections[room_id].discard(websocket)
            logger.info("websocket_removed_from_gateway", room_id=room_id, remaining=len(self.connections[room_id]))
            
            if not self.connections[room_id]:
                del self.connections[room_id]
                if room_id in self.tasks:
                    self.tasks[room_id].cancel()
                    del self.tasks[room_id]

    async def _listen_to_room(self, room_id: str) -> None:
        """Background task: listens to Redis and fans out to all connected WebSockets."""
        channel = f"events:room:{room_id}"
        log = logger.bind(room_id=room_id, channel=channel)
        
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        log.info("pubsub_subscribed_for_room")

        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError) as exc:
                    log.warning("pubsub_message_parse_failed", error=str(exc))
                    continue

                await self.broadcast(room_id, data)
                
        except asyncio.CancelledError:
            log.info("pubsub_listener_cancelled_empty_room")
        except Exception:
            log.exception("pubsub_subscription_error")
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                log.warning("pubsub_unsubscribe_failed")

    async def broadcast(self, room_id: str, message: dict) -> None:
        """Fan out a message to all WebSocket connections in a room concurrently."""
        connections = self.connections.get(room_id, set())
        if not connections:
            return

        async def _safe_send(ws: WebSocket) -> bool:
            try:
                await ws.send_json(message)
                return True
            except Exception:
                return False

        # Fire all sends concurrently so one slow client doesn't block the rest
        results = await asyncio.gather(*[_safe_send(ws) for ws in connections])
        failed = results.count(False)

        if failed > 0:
            logger.warning("broadcast_send_failed", room_id=room_id, failed=failed)