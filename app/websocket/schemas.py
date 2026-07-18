from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field

class BaseClientEvent(BaseModel):
    type: str

class JoinEvent(BaseClientEvent):
    type: Literal["join"] = "join"
    user: str

class TopicEvent(BaseClientEvent):
    type: Literal["topic"] = "topic"
    text: str

class StartEvent(BaseClientEvent):
    type: Literal["start"] = "start"

class BeginEvent(BaseClientEvent):
    type: Literal["begin"] = "begin"

class AnswerEvent(BaseClientEvent):
    type: Literal["answer"] = "answer"
    player_id: str
    selected: int
    time_taken: int = 0

class RejoinEvent(BaseClientEvent):
    type: Literal["rejoin"] = "rejoin"
    player_id: str
    user: str | None = None

class ForceStartEvent(BaseClientEvent):
    """Host forces game to start with whatever topics have been collected so far."""
    type: Literal["force_start"] = "force_start"

class ChatEvent(BaseClientEvent):
    type: Literal["chat"] = "chat"
    message: str

class KickEvent(BaseClientEvent):
    """Host removes a player from the lobby."""
    type: Literal["kick"] = "kick"
    player_id: str

class ConfigureEvent(BaseClientEvent):
    """Host sets game difficulty and question count before starting."""
    type: Literal["configure"] = "configure"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    question_count: int = 15

# A discriminated union based on the "type" field
class LeaveEvent(BaseClientEvent):
    """Player intentionally leaves the lobby."""
    type: Literal["leave"] = "leave"

ClientEventPayload = Annotated[
    Union[
        JoinEvent,
        TopicEvent,
        StartEvent,
        BeginEvent,
        AnswerEvent,
        RejoinEvent,
        ForceStartEvent,
        ChatEvent,
        KickEvent,
        ConfigureEvent,
        LeaveEvent,
    ],
    Field(discriminator="type")
]

from pydantic import TypeAdapter

# Use TypeAdapter to validate incoming JSON directly against the discriminated union.
ClientEventAdapter = TypeAdapter(ClientEventPayload)
