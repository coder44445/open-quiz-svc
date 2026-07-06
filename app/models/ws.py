from pydantic import BaseModel
from typing import Optional, Literal


class WSMessage(BaseModel):
    type: Literal["join", "topic", "start", "answer"]
    user: Optional[str] = None
    text: Optional[str] = None
    answer: Optional[int] = None