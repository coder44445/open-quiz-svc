from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.question.difficutly import Difficulty


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class GenerationJob:
    job_id: str
    room_id: str
    topics: list[dict[str, str]] | list[str]
    difficulty: Difficulty
    count: int
    status: JobStatus = JobStatus.PENDING
