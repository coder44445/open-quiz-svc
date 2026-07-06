from __future__ import annotations

from app.domain.game.session import GameSession
from app.domain.game.answer import Answer


class ScoringService:
    """
    Pure scoring logic.
    No Redis, no API, no state mutation outside session.
    """

    BASE_SCORE = 100
    TIME_BONUS = 50

    def score(self, session: GameSession, answer: Answer) -> int:
        question = session.get_current_question()

        if not question:
            return 0

        correct = answer.selected_index == question.correct_index

        if not correct:
            return 0

        speed_factor = max(0.0, 1.0 - (answer.time_taken / session.time_limit))
        return int(self.BASE_SCORE + (self.TIME_BONUS * speed_factor))