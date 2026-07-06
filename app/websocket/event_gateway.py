import asyncio
import json

from app.core.redis import redis


class EventGateway:
    """
    Listens to Redis Pub/Sub and forwards events to WebSocket clients.
    """

    def __init__(self):
        self.connections: dict[str, set] = {}

    async def subscribe(self, room_id: str, websocket):
        channel = f"events:room:{room_id}"
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)

        if room_id not in self.connections:
            self.connections[room_id] = set()

        self.connections[room_id].add(websocket)

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            data = json.loads(message["data"])

            await self.broadcast(room_id, data)

    async def broadcast(self, room_id: str, message: dict):
        for ws in self.connections.get(room_id, []):
            await ws.send_json(message)