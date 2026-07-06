from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LeaderboardEntry:
    """
    Represents a player's position in the leaderboard.
    """

    player_id: str
    player_name: str
    score: int