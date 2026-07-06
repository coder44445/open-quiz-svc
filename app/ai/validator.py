from __future__ import annotations

from app.domain.question.model import Question


def validate_questions(raw_questions: list[dict], expected_count: int) -> list[Question]:
    if not isinstance(raw_questions, list):
        raise ValueError("AI output must be a list of questions")

    questions: list[Question] = []

    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            raise ValueError("Each question must be an object")

        question_text = raw.get("question")
        options = raw.get("options")
        correct_index = raw.get("correct_index")
        topic = raw.get("topic")

        if not isinstance(question_text, str) or not question_text.strip():
            raise ValueError("Question text is required")

        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("Each question must include at least two options")

        if not isinstance(correct_index, int) or not (0 <= correct_index < len(options)):
            raise ValueError("correct_index must be a valid option index")

        if not isinstance(topic, str) or not topic.strip():
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
        raise ValueError(
            f"Expected {expected_count} questions, but AI returned {len(questions)}"
        )

    return questions
