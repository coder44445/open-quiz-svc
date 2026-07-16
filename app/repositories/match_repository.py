from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.database.models.match import Match
from app.infrastructure.database.models.match_player import MatchPlayer
from app.infrastructure.database.models.question import Question
from app.infrastructure.database.models.answer import Answer


class MatchRepository:
    """Persists match records."""

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

    async def list_finished(self, limit: int = 20, offset: int = 0) -> list[Match]:
        result = await self.session.execute(
            select(Match)
            .where(Match.state == "finished")
            .order_by(desc(Match.finished_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_questions(self, match_id: int) -> list[Question]:
        result = await self.session.execute(
            select(Question)
            .where(Question.match_id == match_id)
            .order_by(Question.order)
        )
        return list(result.scalars().all())

    async def get_players(self, match_id: int) -> list[MatchPlayer]:
        result = await self.session.execute(
            select(MatchPlayer)
            .where(MatchPlayer.match_id == match_id)
            .options(selectinload(MatchPlayer.player))
        )
        return list(result.scalars().all())

    async def get_answers(self, match_id: int) -> list[Answer]:
        result = await self.session.execute(
            select(Answer).where(Answer.match_id == match_id)
        )
        return list(result.scalars().all())

    async def list_by_player(
        self, player_id: str, limit: int = 20, offset: int = 0
    ) -> list[Match]:
        """Return finished matches a specific player participated in."""
        result = await self.session.execute(
            select(Match)
            .join(MatchPlayer, MatchPlayer.match_id == Match.id)
            .where(
                MatchPlayer.player_id == player_id,
                Match.state == "finished",
            )
            .order_by(desc(Match.finished_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
