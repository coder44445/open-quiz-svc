from enum import Enum


class GameState(str, Enum):
    LOBBY = "lobby"
    GENERATING = "generating"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    ABANDONED = "abandoned"