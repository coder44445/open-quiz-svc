from __future__ import annotations

import json

import structlog

from app.core.redis import redis
from app.domain.events import GameEvent

logger = structlog.get_logger(__name__)


class GameEventBus:
    """Central event broadcaster using Redis Pub/Sub.

    Every game event is serialised to JSON and published on a per-room
    channel so all connected gateway instances receive it, regardless of
    which application pod the event originated from.
    """

    PREFIX = "events:room:"

    async def publish(self, event: GameEvent) -> None:
        """Publish a game event to the room's Pub/Sub channel.

        Args:
            event: The GameEvent to broadcast.  The type field is treated
                   as the message discriminator by subscribers.
        """

        channel = self.PREFIX + event.room_id

        try:
            await redis.publish(
                channel,
                json.dumps({
                    "type": event.type,
                    "room_id": event.room_id,
                    "payload": event.payload,
                }),
            )
            logger.debug(
                "event_published",
                channel=channel,
                event_type=event.type,
                room_id=event.room_id,
            )
        except Exception:
            logger.exception(
                "event_publish_failed",
                channel=channel,
                event_type=event.type,
                room_id=event.room_id,
            )
            raise