from __future__ import annotations

import structlog
from pydantic import BaseModel, Field, ValidationError, model_validator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai.providers.ollama import OllamaProvider

from app.domain.question.model import Question

logger = structlog.get_logger(__name__)

class GeneratedQuestionSchema(BaseModel):
    """Pydantic schema defining the strict structure expected from the AI provider."""
    question: str = Field(..., min_length=1)
    options: list[str] = Field(..., min_length=2)
    correct_index: int
    topic: str = Field(..., min_length=1)
    difficulty: str = Field(..., min_length=1)

    @model_validator(mode='after')
    def validate_correct_index(self) -> "GeneratedQuestionSchema":
        if not (0 <= self.correct_index < len(self.options)):
            raise ValueError(f"correct_index {self.correct_index} is out of bounds for options")
        
        # Enforce True/False strictness
        if len(self.options) == 2:
            if [o.lower() for o in self.options] != ["true", "false"]:
                raise ValueError("If a question has 2 options, they must be 'True' and 'False'.")
        # Enforce MCQ strictness
        elif len(self.options) != 4:
            raise ValueError(f"Questions must have either 2 options (True/False) or 4 options (MCQ), got {len(self.options)}")
            
        return self


def validate_questions(raw_questions: list[dict], expected_count: int) -> list[Question]:
    """Validate and coerce raw AI output into Question domain objects using Pydantic.

    Args:
        raw_questions:  List of dicts as returned by the AI provider.
        expected_count: Exact number of valid questions required.

    Returns:
        List of Question objects in the same order as the input.

    Raises:
        ValueError: If any question is structurally invalid or the count
                    does not match expected_count.
    """

    if not isinstance(raw_questions, list):
        logger.error(
            "question_validation_failed",
            reason="ai_output_not_a_list",
            actual_type=type(raw_questions).__name__,
        )
        raise ValueError("AI output must be a list of questions")

    if len(raw_questions) != expected_count:
        logger.error(
            "question_count_mismatch",
            expected=expected_count,
            actual=len(raw_questions),
        )
        raise ValueError(
            f"Expected {expected_count} questions, but AI returned {len(raw_questions)}"
        )

    questions: list[Question] = []

    for index, raw in enumerate(raw_questions):
        try:
            validated = GeneratedQuestionSchema.model_validate(raw)
        except ValidationError as exc:
            logger.warning(
                "question_validation_field_error",
                index=index,
                errors=exc.errors(),
            )
            raise ValueError(f"Question validation failed: {exc}") from exc

        questions.append(
            Question(
                id=index,
                topic=validated.topic,
                difficulty=validated.difficulty,
                text=validated.question,
                options=validated.options,
                correct_index=validated.correct_index,
            )
        )

    logger.info("question_validation_passed", question_count=len(questions))
    return questions


async def verify_questions(
    questions: list[Question],
    provider: "OllamaProvider",  # type: ignore[name-defined]
) -> list[Question]:
    """Run a second-pass correctness check over a validated question list.

    Two layers of protection:

    1. Heuristic guards — fast, zero LLM cost:
       - All questions in the batch have the same correct_index → model is defaulting,
         mark the whole batch as suspect and skip per-question verification (caller retries).
       - Question text contains negation words ('NOT', 'EXCEPT', 'NEVER') → flag in logs.

    2. Per-question verification — one extra LLM call per question:
       - Ask the model to answer the question as a multiple-choice student.
       - If the verifier picks a different index, override correct_index with the
         verifier's answer and log a warning.
       - If the verifier returns None (unparseable), keep the original — non-fatal.

    Returns the (potentially corrected) question list.
    Raises ValueError only when heuristic checks indicate the entire batch is bad.
    """
    if not questions:
        return questions

    NEGATION_WORDS = {"not", "except", "never", "cannot", "false", "incorrect"}

    all_correct = [q.correct_index for q in questions]

    # If every question points to the same index, the model is not reasoning —
    # it is pattern-matching. Flag it so the worker can retry the batch.
    if len(set(all_correct)) == 1 and len(questions) > 1:
        logger.warning(
            "verify_batch_all_same_index",
            correct_index=all_correct[0],
            question_count=len(questions),
        )
        raise ValueError(
            f"All {len(questions)} questions have correct_index={all_correct[0]} — "
            "model appears to be defaulting. Retrying batch."
        )

    import asyncio

    for q in questions:
        lower_text = q.text.lower()
        has_negation = any(w in lower_text.split() for w in NEGATION_WORDS)
        if has_negation:
            logger.info("verify_negation_question_flagged", question_text=q.text[:80])

    verify_tasks = [provider.verify_question(q.text, q.options) for q in questions]
    verifier_indexes = await asyncio.gather(*verify_tasks)

    verified: list[Question] = []
    for q, verifier_index in zip(questions, verifier_indexes):
        if verifier_index is None:
            # Inconclusive — keep the original and move on
            verified.append(q)
            continue

        if verifier_index != q.correct_index:
            logger.warning(
                "verify_index_mismatch_corrected",
                original=q.correct_index,
                verifier=verifier_index,
                question_text=q.text[:80],
            )
            q.correct_index = verifier_index

        verified.append(q)

    return verified
