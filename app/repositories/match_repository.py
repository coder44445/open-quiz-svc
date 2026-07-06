from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.match import Match


class MatchRepository:
    """
    Persists match records.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, match: Match) -> None:
        self.session.add(match)
        await self.session.flush()

    async def get_by_room(self, room_id: str) -> Match | None:
        result = await self.session.execute(
            select(Match).where(Match.room_id == room_id)
        )
        return result.scalar_one_or_none()

    async def save(self, match: Match) -> None:
        self.session.add(match)
        await self.session.flush()

    save_match = save
