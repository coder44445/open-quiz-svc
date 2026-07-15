from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class Player:
    """
    Represents a participant in a quiz session.
    """

    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    score: int = 0
    is_connected: bool = True

    def add_score(self, points: int) -> None:
        """Increase player score."""
        self.score += points