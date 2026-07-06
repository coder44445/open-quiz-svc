from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GameEvent:
    """
    Base event sent across the system.
    """

    type: str
    room_id: str
    payload: dict[str, Any]