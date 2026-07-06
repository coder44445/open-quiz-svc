from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models.question import Question


class QuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_all(self, questions: list[Question]) -> None:
        self.session.add_all(questions)
        await self.session.flush()

    async def get_by_match(self, match_id: int) -> list[Question]:
        result = await self.session.execute(
            select(Question).where(Question.match_id == match_id).order_by(Question.order)
        )
        return result.scalars().all()
