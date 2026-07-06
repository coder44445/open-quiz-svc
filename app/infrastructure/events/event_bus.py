import json

from app.core.redis import redis
from app.domain.events import GameEvent


class GameEventBus:
    """
    Central event broadcaster using Redis Pub/Sub.
    """

    PREFIX = "events:room:"

    async def publish(self, event: GameEvent) -> None:
        channel = self.PREFIX + event.room_id

        await redis.publish(
            channel,
            json.dumps({
                "type": event.type,
                "room_id": event.room_id,
                "payload": event.payload,
            }),
        )