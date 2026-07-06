from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from app.domain.player.model import Player


@dataclass(slots=True)
class Room:
    """
    Represents a lobby where players gather before a game starts.
    """

    id: str
    host_id: str

    players: Dict[str, Player] = field(default_factory=dict)
    topics: List[str] = field(default_factory=list)

    def add_player(self, player: Player) -> None:
        """Add a player to the room."""
        self.players[player.id] = player

    def remove_player(self, player_id: str) -> None:
        """Remove a player from the room."""
        self.players.pop(player_id, None)

    def add_topic(self, topic: str) -> None:
        """Add a topic submitted by a player."""
        self.topics.append(topic)