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
import random
import time

@dataclass
class GameSession:
    """
    Represents a single running quiz match.

    Owns:
    - players
    - topics
    - questions
    - scores
    - game state
    """

    room_id: str
    match_id: int | None = None

    players: dict[str, Player] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)

    questions: list[Question] = field(default_factory=list)
    answers: dict[str, list[Answer]] = field(default_factory=dict)
    time_limit: int = 60

    state: GameState = GameState.LOBBY
    state_controller: GameStateController = field(default_factory=GameStateController)

    question_started_at: int = 0
    current_question_index: int = 0


    event_bus: GameEventBus | None = None

    def add_player(self, player: Player) -> None:
        self.players[player.id] = player

    def add_topic(self, topic: str) -> None:
        self.topics.append(topic)

    def start(self) -> None:
        """
        Start the game session.
        Selects topics and moves state to RUNNING.
        """
        if len(self.topics) < 1:
            raise ValueError("Cannot start game without topics")

        selected = random.sample(self.topics, min(5, len(self.topics)))

        self.questions = [
            Question(
                id=i,
                topic=t,
                text=f"What is related to {t}?",
                options=["A", "B", "C", "D"],
                correct_index=0,
            )
            for i, t in enumerate(selected)
        ]
    
        self.set_state(GameState.IN_PROGRESS)

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
            ],
            key=lambda x: x.score,
            reverse=True,
        )

    def set_state(self, new_state: GameState) -> None:
        old = self.state

        self.state = self.state_controller.transition(self.state, new_state)

        if self.event_bus:
            asyncio.create_task(
                self.event_bus.publish(
                    GameEvent(
                        type=EventType.GAME_STATE_CHANGED,
                        room_id=self.room_id,
                        payload={
                            "from": old,
                            "to": self.state,
                        },
                    )
                )
            )

    def _sync_session_state(self):
        if not self.event_bus:
            return

        asyncio.create_task(
            self.event_bus.publish(
                GameEvent(
                    type=EventType.SESSION_SYNC,
                    room_id=self.room_id,
                    payload={
                        "current_question_index": self.current_question_index,
                        "state": self.state,
                        "time_limit": self.time_limit,
                    },
                )
            )
        )