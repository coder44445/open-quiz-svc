from math import floor


class ScoringService:
    """
    Calculates the score awarded for a single answer.
    """

    BASE_POINTS = 100
    MAX_BONUS = 50

    @classmethod
    def calculate(
        cls,
        *,
        correct: bool,
        time_taken: float,
        time_limit: float,
    ) -> int:
        if not correct:
            return 0

        ratio = max(0.0, min(1.0, time_taken / time_limit))
        bonus = floor(cls.MAX_BONUS * (1 - ratio))

        return cls.BASE_POINTS + bonus