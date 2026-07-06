from __future__ import annotations

from typing import Protocol

from app.domain.question.difficutly import Difficulty
from app.domain.question.model import Question


class AIProvider(Protocol):
    """Contract implemented by every LLM provider."""

    async def generate_questions(
        self,
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> list[Question]:
        ...
