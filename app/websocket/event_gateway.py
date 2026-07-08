from __future__ import annotations

import asyncio
import json

import structlog

from fastapi import WebSocket

from app.core.redis import redis

logger = structlog.get_logger(__name__)


class EventGateway:
    """Listens to Redis Pub/Sub and forwards events to WebSocket clients.

    One subscription is created per room per connected client.  All active
    WebSocket connections for a room are tracked in ``self.connections`` so
    that a single Pub/Sub message is fanned out to every subscriber.
    """

    def __init__(self) -> None:
        # Maps room_id → set of active WebSocket connections.
        self.connections: dict[str, set] = {}

    async def subscribe(self, room_id: str, websocket: WebSocket) -> None:
        """Subscribe to room events and forward them to the given WebSocket.

        Starts listening on the Redis channel ``events:room:<room_id>`` and
        calls ``broadcast`` for every message that arrives.  Returns when the
        Pub/Sub connection is closed (e.g. on WebSocket disconnect or Redis
        error).

        Args:
            room_id:   The quiz room to subscribe to.
            websocket: The client WebSocket connection to forward events to.
        """

        channel = f"events:room:{room_id}"
        log = logger.bind(room_id=room_id, channel=channel)

        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)

        if room_id not in self.connections:
            self.connections[room_id] = set()

        self.connections[room_id].add(websocket)
        connection_count = len(self.connections[room_id])

        log.info("pubsub_subscribed", active_connections=connection_count)

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
            # Normal path when the WebSocket task is cancelled on disconnect.
            log.info("pubsub_subscription_cancelled")
            raise

        except Exception:
            log.exception("pubsub_subscription_error")

        finally:
            # Clean up the connection from the tracking set.
            self.connections.get(room_id, set()).discard(websocket)
            remaining = len(self.connections.get(room_id, set()))
            log.info("pubsub_unsubscribed", remaining_connections=remaining)

            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                log.warning("pubsub_unsubscribe_failed")

    async def broadcast(self, room_id: str, message: dict) -> None:
        """Fan out a message to all WebSocket connections in a room.

        Failed sends are logged and skipped so a single broken connection
        does not prevent other clients from receiving the event.

        Args:
            room_id: The target quiz room.
            message: JSON-serialisable dict to send.
        """

        connections = self.connections.get(room_id, set())

        if not connections:
            logger.debug("broadcast_no_connections", room_id=room_id)
            return

        failed = 0
        for ws in list(connections):
            try:
                await ws.send_json(message)
            except Exception:
                failed += 1
                logger.warning(
                    "broadcast_send_failed",
                    room_id=room_id,
                    event_type=message.get("type"),
                )

        logger.debug(
            "broadcast_sent",
            room_id=room_id,
            event_type=message.get("type"),
            recipients=len(connections) - failed,
            failed=failed,
        )