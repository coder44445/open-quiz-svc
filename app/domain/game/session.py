from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.game.state import GameState
from app.domain.game.controller import GameStateController
from app.domain.player.model import Player
from app.domain.question.model import Question
from app.domain.game.answer import Answer
from app.domain.game.leaderboard import LeaderboardEntry

from app.domain.event_types import EventType
from app.domain.events import GameEvent
from app.infrastructure.events.event_bus import GameEventBus

import asyncio
import time

@dataclass
class GameSession:
    """
    Represents a single running quiz match.

    [ARCHITECTURE INTENT: Pure State Machine]
    This class is the absolute source of truth for a game room. It manages all 
    data (players, scores, topics, active question) and enforces state machine 
    transitions (e.g., LOBBY -> IN_PROGRESS -> FINISHED) via the state_controller.
    
    Because this is cached in Redis, it must remain serialisable as a pure dataclass.
    Avoid injecting active I/O clients (like DB sessions) directly into this model.
    """

    room_id: str
    match_id: int | None = None

    players: dict[str, Player] = field(default_factory=dict)
    host_id: str | None = None
    topics: list[dict[str, str]] = field(default_factory=list)
    chosen_topic_submitters: list[str] = field(default_factory=list)
    pending_topic_submitters: list[str] = field(default_factory=list)

    questions: list[Question] = field(default_factory=list)
    answers: dict[str, list[Answer]] = field(default_factory=dict)
    time_limit: int = 60
    difficulty: str = "medium"
    question_count: int = 15

    state: GameState = GameState.LOBBY
    state_controller: GameStateController = field(default_factory=GameStateController)

    question_started_at: int = 0
    current_question_index: int = 0


    event_bus: GameEventBus | None = None

    def add_player(self, player: Player) -> None:
        """Register a player in this session."""
        if not self.players:
            self.host_id = player.id

        self.players[player.id] = player

    def add_topic(self, topic: dict[str, str]) -> None:
        """Append a topic to the pool used for question generation."""
        self.topics.append(topic)

    def get_current_question(self) -> Question | None:
        """Return current question."""
        if self.current_question_index >= len(self.questions):
            return None
        return self.questions[self.current_question_index]

    def next_question(self) -> None:
        """Move to next question."""
        self.current_question_index += 1
        self.question_started_at = int(time.time())

        self._sync_session_state()

        if self.current_question_index >= len(self.questions):
            self.state = GameState.FINISHED

    def submit_answer(self, answer: Answer) -> bool:
        """
        Returns True if accepted, False if rejected.
        """
    
        key = str(self.current_question_index)
    
        if key not in self.answers:
            self.answers[key] = []
    
        # prevent duplicate answers
        for existing in self.answers[key]:
            if existing.player_id == answer.player_id:
                return False
    
        # reject late answers (simple guard)
        if self.state != GameState.IN_PROGRESS:
            return False
    
        self.answers[key].append(answer)
        return True

    def apply_score(self, player_id: str, score: int) -> None:
        
        if player_id in self.players:
            self.players[player_id].score += score
        
    def is_finished(self) -> bool:
        return self.state.name == "FINISHED"

    def all_players_answered(self) -> bool:
        """Return True if every player in the session has submitted an answer."""
        if not self.players:
            return False
        key = str(self.current_question_index)
        answered_ids = {a.player_id for a in self.answers.get(key, [])}
        active_players = [pid for pid, p in self.players.items() if not p.is_spectator]
        if not active_players:
            return True
        return all(pid in answered_ids for pid in active_players)

    def current_question_dict(self) -> dict | None:
        """Return the current question as a JSON-serialisable dict, or None."""
        q = self.get_current_question()
        if q is None:
            return None
        return {
            "id": q.id,
            "topic": q.topic,
            "text": q.text,
            "options": q.options,
            "correct_index": q.correct_index,
        }

    def get_leaderboard(self) -> list[LeaderboardEntry]:
        """
        Build sorted leaderboard from player scores.
        """
    
        return sorted(
            [
                LeaderboardEntry(
                    player_id=p.id,
                    player_name=p.name,
                    score=p.score,
                )
                for p in self.players.values()
                if not p.is_spectator
            ],
            key=lambda x: x.score,
            reverse=True,
        )

    def set_state(self, new_state: GameState) -> None:
        """Transition to a new state via the state controller.

        Publishes a GAME_STATE_CHANGED event if an event bus is attached.
        Payloads use .value (plain string) so they are JSON-serialisable.
        """
        old = self.state

        self.state = self.state_controller.transition(self.state, new_state)

        if self.event_bus:
            asyncio.create_task(
                self.event_bus.publish(
                    GameEvent(
                        type=EventType.GAME_STATE_CHANGED,
                        room_id=self.room_id,
                        payload={
                            # Use .value so the payload is JSON-serialisable.
                            "from": old.value,
                            "to": self.state.value,
                        },
                    )
                )
            )

    def _sync_session_state(self) -> None:
        """Publish the current question index, state, and time limit to subscribers.

        Called by next_question() after every question advance so reconnecting
        clients receive an up-to-date snapshot.  Payloads use .value so they
        are JSON-serialisable.
        """
        if not self.event_bus:
            return

        asyncio.create_task(
            self.event_bus.publish(
                GameEvent(
                    type=EventType.SESSION_SYNC,
                    room_id=self.room_id,
                    payload={
                        "current_question_index": self.current_question_index,
                        # Use .value so the payload is JSON-serialisable.
                        "state": self.state.value,
                        "time_limit": self.time_limit,
                    },
                )
            )
        )