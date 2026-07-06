from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Answer:
    """
    Represents a player's answer to a question.
    """

    player_id: str
    question_id: int
    selected_index: int
    time_taken: float