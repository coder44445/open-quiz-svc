from __future__ import annotations

import structlog
from pydantic import BaseModel, Field, ValidationError, model_validator

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
                text=validated.question,
                options=validated.options,
                correct_index=validated.correct_index,
            )
        )

    logger.info("question_validation_passed", question_count=len(questions))
    return questions
