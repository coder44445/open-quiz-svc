from __future__ import annotations

import structlog

from app.domain.question.model import Question

logger = structlog.get_logger(__name__)


def validate_questions(raw_questions: list[dict], expected_count: int) -> list[Question]:
    """Validate and coerce raw AI output into Question domain objects.

    Iterates over each raw dict and enforces the minimum required fields.
    Raises ValueError with a descriptive message on the first invalid entry
    so callers can decide whether to retry or fail the job.

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

    questions: list[Question] = []

    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            logger.warning(
                "question_skipped",
                index=index,
                reason="not_a_dict",
                actual_type=type(raw).__name__,
            )
            raise ValueError("Each question must be an object")

        question_text = raw.get("question")
        options = raw.get("options")
        correct_index = raw.get("correct_index")
        topic = raw.get("topic")

        # Validate each required field and log exactly what is wrong.
        if not isinstance(question_text, str) or not question_text.strip():
            logger.warning("question_validation_field_error", index=index, field="question")
            raise ValueError("Question text is required")

        if not isinstance(options, list) or len(options) < 2:
            logger.warning(
                "question_validation_field_error",
                index=index,
                field="options",
                options_count=len(options) if isinstance(options, list) else None,
            )
            raise ValueError("Each question must include at least two options")

        if not isinstance(correct_index, int) or not (0 <= correct_index < len(options)):
            logger.warning(
                "question_validation_field_error",
                index=index,
                field="correct_index",
                correct_index=correct_index,
                options_count=len(options),
            )
            raise ValueError("correct_index must be a valid option index")

        if not isinstance(topic, str) or not topic.strip():
            logger.warning("question_validation_field_error", index=index, field="topic")
            raise ValueError("Topic is required for each question")

        questions.append(
            Question(
                id=index,
                topic=topic,
                text=question_text,
                options=options,
                correct_index=correct_index,
            )
        )

    if len(questions) != expected_count:
        logger.error(
            "question_count_mismatch",
            expected=expected_count,
            actual=len(questions),
        )
        raise ValueError(
            f"Expected {expected_count} questions, but AI returned {len(questions)}"
        )

    logger.info("question_validation_passed", question_count=len(questions))
    return questions
