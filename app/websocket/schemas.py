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

class ForceStartEvent(BaseClientEvent):
    """Host forces game to start with whatever topics have been collected so far."""
    type: Literal["force_start"] = "force_start"

class ChatEvent(BaseClientEvent):
    type: Literal["chat"] = "chat"
    message: str

# A discriminated union based on the "type" field
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
    ],
    Field(discriminator="type")
]

from pydantic import TypeAdapter

# Use TypeAdapter to validate incoming JSON directly against the discriminated union.
ClientEventAdapter = TypeAdapter(ClientEventPayload)
