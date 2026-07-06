from enum import Enum
from pydantic import BaseModel, Field


class GameStatus(str, Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


class Question(BaseModel):
    id: int
    topic: str
    question: str
    options: list[str]
    correct_answer: int


class PlayerAnswer(BaseModel):
    player_id: str
    question_id: int
    selected_option: int
    time_taken: float = Field(ge=0)