from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.match_player import MatchPlayer


class MatchPlayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, match_player: MatchPlayer) -> None:
        self.session.add(match_player)
        await self.session.flush()

    async def get_by_match_and_player(
        self,
        match_id: int,
        player_id: str,
    ) -> MatchPlayer | None:
        result = await self.session.execute(
            select(MatchPlayer).where(
                MatchPlayer.match_id == match_id,
                MatchPlayer.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_match(self, match_id: int) -> list[MatchPlayer]:
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(MatchPlayer)
            .where(MatchPlayer.match_id == match_id)
            .options(selectinload(MatchPlayer.player))
        )
        return list(result.scalars().all())
