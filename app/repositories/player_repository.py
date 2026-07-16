from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.player import Player


class PlayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, player: Player) -> None:
        self.session.add(player)
        await self.session.flush()

    async def get(self, player_id: str) -> Player | None:
        return await self.session.get(Player, player_id)
