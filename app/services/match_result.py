from __future__ import annotations

from dataclasses import dataclass

from app.domain.game.leaderboard import LeaderboardEntry


@dataclass(slots=True)
class MatchResult:
    """
    Final snapshot of a completed game.
    """

    room_id: str
    leaderboard: list[LeaderboardEntry]
    total_questions: int