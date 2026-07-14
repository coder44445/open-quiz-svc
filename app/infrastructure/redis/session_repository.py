from __future__ import annotations

import json
import dataclasses

import structlog

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

logger = structlog.get_logger(__name__)


class SessionRepository:
    """Redis-backed storage for active GameSessions.

    Stores serialised sessions in Redis for fast reads and writes during
    active gameplay.  If a session is not found in Redis (e.g. after a
    restart or cache eviction) it is rehydrated from the PostgreSQL database
    to ensure sessions survive Redis restarts.

    This makes the application horizontally scalable: any pod that holds
    the Redis client can serve any room.
    """

    def __init__(self) -> None:
        self.redis = create_redis_client()

    async def save(self, session: GameSession) -> None:
        """Serialise and persist session state to Redis."""

        key = f"session:{session.room_id}"
        # Set a 2-hour TTL. Active games will constantly refresh this TTL on state changes.
        # This prevents Redis memory leaks if the server crashes and remove_player isn't called.
        await self.redis.set(key, json.dumps(self._serialize(session)), ex=7200)
        logger.debug("session_saved", room_id=session.room_id, state=session.state.value)

    async def get(self, room_id: str) -> GameSession | None:
        """Load session from Redis.

        Falls back to database rehydration if the key is not present in Redis
        (cold-start or cache eviction).

        Returns:
            Hydrated GameSession, or None if the room has no match record.
        """

        data = await self.redis.get(f"session:{room_id}")

        if not data:
            logger.info("session_cache_miss", room_id=room_id)
            return await self._rehydrate_from_database(room_id)

        raw = json.loads(data)
        session = GameSession(room_id=raw["room_id"])
        # Attach event bus so the domain session can publish sync/state events.
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
        """Remove session from Redis (e.g. after the match is fully finished)."""

        await self.redis.delete(f"session:{room_id}")
        logger.info("session_deleted", room_id=room_id)

    async def _rehydrate_from_database(self, room_id: str) -> GameSession | None:
        """Rebuild a GameSession from durable storage after a cache miss.

        Loads match, questions, players, and answers from PostgreSQL and
        re-creates the session object in memory.  The result is NOT written
        back to Redis here; callers that mutate the session will persist it
        via save().
        """

        logger.info("session_rehydrating_from_db", room_id=room_id)

        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(room_id)
            if not match:
                logger.warning("session_rehydration_failed", room_id=room_id, reason="match_not_found")
                return None

            questions = await uow.questions.get_by_match(match.id)
            match_players = await uow.match_players.get_by_match(match.id)
            answers = await uow.answers.get_by_match(match.id)

            session = GameSession(room_id=room_id)
            # Attach event bus for publishing session sync events.
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

        logger.info(
            "session_rehydrated",
            room_id=room_id,
            state=session.state.value,
            player_count=len(session.players),
            question_count=len(session.questions),
        )

        return session

    def _serialize(self, session: GameSession) -> dict:
        """Convert a GameSession to a plain dict suitable for JSON serialisation."""

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
            "questions": [dataclasses.asdict(question) for question in session.questions],
            "answers": {
                question_id: [dataclasses.asdict(answer) for answer in answers]
                for question_id, answers in session.answers.items()
            },
            "time_limit": session.time_limit,
            "state": session.state.value,
            "question_started_at": session.question_started_at,
            "current_question_index": session.current_question_index,
        }
