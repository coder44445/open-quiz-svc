from __future__ import annotations

import json

from app.domain.game.session import GameSession
from app.domain.player.model import Player
from app.domain.question.model import Question
from app.domain.game.answer import Answer
from app.domain.game.state import GameState
from app.infrastructure.database.models.match import Match
from app.infrastructure.database.models.answer import Answer as AnswerModel
from app.infrastructure.database.models.match_player import MatchPlayer
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.events.event_bus import GameEventBus
from app.infrastructure.redis.client import create_redis_client


class SessionRepository:
    """
    Redis-backed storage for active GameSessions.

    This makes the system horizontally scalable.
    """

    def __init__(self) -> None:
        self.redis = create_redis_client()

    async def save(self, session: GameSession) -> None:
        """Persist session state in Redis."""
        await self.redis.set(
            f"session:{session.room_id}",
            json.dumps(self._serialize(session)),
        )

    async def get(self, room_id: str) -> GameSession | None:
        """Load session from Redis or rehydrate from durable storage."""
        data = await self.redis.get(f"session:{room_id}")

        if not data:
            return await self._rehydrate_from_database(room_id)

        raw = json.loads(data)
        session = GameSession(room_id=raw["room_id"])
        # attach event bus so domain session can publish sync/state events
        session.event_bus = GameEventBus()
        session.match_id = raw.get("match_id")
        session.players = {
            player_id: Player(**player_data)
            for player_id, player_data in raw.get("players", {}).items()
        }
        session.topics = raw.get("topics", [])
        session.questions = [Question(**question) for question in raw.get("questions", [])]
        session.answers = {
            question_id: [Answer(**answer) for answer in answers]
            for question_id, answers in raw.get("answers", {}).items()
        }
        session.time_limit = raw.get("time_limit", 60)
        session.state = GameState(raw.get("state", GameState.LOBBY.value))
        session.question_started_at = raw.get("question_started_at", 0)
        session.current_question_index = raw.get("current_question_index", 0)

        return session

    async def delete(self, room_id: str) -> None:
        """Delete session from Redis."""
        await self.redis.delete(f"session:{room_id}")

    async def _rehydrate_from_database(self, room_id: str) -> GameSession | None:
        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(room_id)
            if not match:
                return None

            questions = await uow.questions.get_by_match(match.id)
            match_players = await uow.match_players.get_by_match(match.id)
            answers = await uow.answers.get_by_match(match.id)

            session = GameSession(room_id=room_id)
            # attach event bus for publishing session sync events
            session.event_bus = GameEventBus()
            session.match_id = match.id
            session.state = GameState(match.state)
            session.questions = [Question(**question.question_json) for question in questions]
            session.players = {
                player_entry.player.id: Player(
                    name=player_entry.player.name,
                    id=player_entry.player.id,
                )
                for player_entry in match_players
                if player_entry.player is not None
            }
            for answer_row in answers:
                question_key = str(answer_row.question_id)
                session.answers.setdefault(question_key, [])
                session.answers[question_key].append(
                    Answer(
                        player_id=answer_row.player_id,
                        question_id=answer_row.question_id,
                        selected_index=answer_row.selected_option,
                        time_taken=answer_row.time_taken,
                    )
                )

            session.current_question_index = 0
            session.question_started_at = 0
            return session

    def _serialize(self, session: GameSession) -> dict:
        return {
            "room_id": session.room_id,
            "match_id": session.match_id,
            "players": {
                player_id: {
                    "id": player.id,
                    "name": player.name,
                    "score": player.score,
                }
                for player_id, player in session.players.items()
            },
            "topics": session.topics,
            "questions": [question.__dict__ for question in session.questions],
            "answers": {
                question_id: [answer.__dict__ for answer in answers]
                for question_id, answers in session.answers.items()
            },
            "time_limit": session.time_limit,
            "state": session.state.value,
            "question_started_at": session.question_started_at,
            "current_question_index": session.current_question_index,
        }
