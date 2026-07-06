from app.ai.providers.base import AIProvider
from app.ai.validator import validate_questions
from app.domain.question.difficutly import Difficulty
from app.domain.question.model import Question


class AIEngine:

    def __init__(self, provider: AIProvider):
        self.provider = provider

    async def generate_questions(
        self,
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> list[Question]:
        raw_questions = await self.provider.generate_questions(
            topics=topics,
            difficulty=difficulty,
            count=count,
        )

        return validate_questions(raw_questions, count)
