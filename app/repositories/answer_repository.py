from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.answer import Answer
from app.infrastructure.database.models.question import Question


class AnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, answer: Answer) -> None:
        self.session.add(answer)
        await self.session.flush()

    async def get_by_question_and_player(self, question_id: int, player_id: str) -> Answer | None:
        result = await self.session.execute(
            select(Answer).where(
                Answer.question_id == question_id,
                Answer.player_id == player_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_match(self, match_id: int) -> list[Answer]:
        result = await self.session.execute(
            select(Answer).where(
                Answer.question_id.in_(
                    select(Question.id).where(Question.match_id == match_id)
                )
            )
        )
        return result.scalars().all()
