from __future__ import annotations

import time

import structlog

from app.ai.providers.base import AIProvider
from app.ai.validator import validate_questions
from app.domain.question.difficutly import Difficulty
from app.domain.question.model import Question

logger = structlog.get_logger(__name__)


class AIEngine:
    """Thin orchestrator between AI providers and question validation.

    Delegates raw generation to the injected provider and then validates the
    output through a shared validator so validation logic is provider-agnostic.
    """

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider

    async def generate_questions(
        self,
        topics: list[str],
        difficulty: Difficulty,
        count: int,
    ) -> list[Question]:
        """Generate and validate quiz questions.

        Args:
            topics:     List of topic strings to generate questions for.
            difficulty: Target difficulty level.
            count:      Exact number of questions expected.

        Returns:
            Validated list of Question domain objects.

        Raises:
            ValueError: If the provider returns unexpected output or validation fails.
        """

        log = logger.bind(
            provider=type(self.provider).__name__,
            topic_count=len(topics),
            difficulty=difficulty.value,
            count=count,
        )

        log.info("ai_generation_started")
        start = time.perf_counter()

        raw_questions = await self.provider.generate_questions(
            topics=topics,
            difficulty=difficulty,
            count=count,
        )

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info("ai_generation_raw_received", raw_count=len(raw_questions), elapsed_ms=elapsed_ms)

        # Validate the raw provider output against the domain Question schema.
        questions = validate_questions(raw_questions, count)

        log.info("ai_generation_validated", question_count=len(questions))
        return questions
