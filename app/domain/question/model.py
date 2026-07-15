from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Question:
    """
    A quiz question generated from a topic.
    """

    id: int
    topic: str
    difficulty: str
    text: str
    options: list[str]
    correct_index: int