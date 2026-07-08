from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Type

from app.core.logging import logger
from app.domain.game.session import GameSession
from app.domain.player.model import Player
from app.domain.question.difficutly import Difficulty
from app.domain.game.state import GameState
from app.infrastructure.redis.session_repository import SessionRepository
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.database.models.match import Match
from app.infrastructure.database.models.player import Player as PlayerModel
from app.infrastructure.database.models.match_player import MatchPlayer
from app.services.question_service import create_generation_job


class GameService:
    """Orchestrates game actions and state transitions.

    Owns a GameLoop instance so callers can do::

        session = await service.begin_play(room_id)
        result  = await service.loop.run(room_id)   # blocks until game ends

    The loop is imported lazily to avoid a circular import between game_service
    and game_loop (both depend on SessionRepository).
    """

    def __init__(self, unit_of_work_factory: Type[UnitOfWork] | None = None) -> None:
        self.store = SessionRepository()
        self.uow_factory = unit_of_work_factory or UnitOfWork

        # Lazy import breaks the circular dependency:
        #   game_service → game_loop → game_service
        from app.services.game_loop import GameLoop
        self.loop = GameLoop(service=self, unit_of_work_factory=self.uow_factory)

    async def create_session(self, room_id: str) -> GameSession:
        """Create a new lobby session and persist a Match record to the DB."""

        session = GameSession(room_id=room_id)
        logger.info("session_create_requested", room_id=room_id)

        async with self.uow_factory() as uow:
            match = Match(room_id=room_id, state=GameState.LOBBY.value)
            await uow.matches.add(match)
            session.match_id = match.id

        await self.store.save(session)
        logger.info(
            "session_created",
            room_id=room_id,
            match_id=session.match_id,
        )
        return session

    async def get_session(self, room_id: str) -> GameSession | None:
        """Return the active session for a room, or None if it does not exist."""
        return await self.store.get(room_id)

    async def add_player(self, room_id: str, player: Player) -> None:
        """Add a player to a room, creating the session if it does not exist yet.

        Also upserts the Player and MatchPlayer rows in the database so the
        player record is durable even if Redis is flushed.
        """

        session = await self.store.get(room_id)

        if not session:
            logger.info("session_missing_for_player_join", room_id=room_id)
            session = await self.create_session(room_id)

        session.add_player(player)
        await self.store.save(session)
        logger.info(
            "player_added",
            room_id=room_id,
            player_id=player.id,
            player_name=player.name,
            player_count=len(session.players),
        )

        if session.match_id is not None:
            async with self.uow_factory() as uow:
                existing = await uow.players.get(player.id)
                if not existing:
                    await uow.players.save(PlayerModel(id=player.id, name=player.name))

                match_player = await uow.match_players.get_by_match_and_player(
                    session.match_id,
                    player.id,
                )
                if not match_player:
                    await uow.matches.add(
                        MatchPlayer(
                            match_id=session.match_id,
                            player_id=player.id,
                        )
                    )

    async def add_topic(self, room_id: str, topic: str) -> None:
        """Append a topic to the session's topic list.

        Creates the session if it does not exist yet (host may send topics
        before any player has joined).
        """

        session = await self.store.get(room_id)

        if not session:
            logger.info("session_missing_for_topic_add", room_id=room_id)
            session = await self.create_session(room_id)

        session.add_topic(topic)
        await self.store.save(session)
        logger.info(
            "topic_added",
            room_id=room_id,
            topic=topic,
            topic_count=len(session.topics),
        )

    async def start_game(self, room_id: str, count: int = 5) -> GameSession:
        """Transition the session to GENERATING and enqueue an AI question-generation job.

        Args:
            room_id: Target quiz room.
            count:   Number of questions to generate.

        Raises:
            ValueError: If the session does not exist, is not in LOBBY state,
                        or has no topics.
        """

        session = await self.store.get(room_id)

        if not session:
            logger.warning("game_start_failed", room_id=room_id, reason="session_not_found")
            raise ValueError("Session not found")

        if session.state != GameState.LOBBY:
            logger.warning(
                "game_start_failed",
                room_id=room_id,
                reason="invalid_state",
                state=session.state.name,
            )
            raise ValueError("Game can only start from lobby")

        if not session.topics:
            logger.warning("game_start_failed", room_id=room_id, reason="no_topics")
            raise ValueError("Cannot start game without topics")

        session.set_state(GameState.GENERATING)
        await self.store.save(session)
        logger.info(
            "game_start_requested",
            room_id=room_id,
            topic_count=len(session.topics),
            requested_question_count=count,
        )

        # Mirror the state change to the durable match record.
        async with self.uow_factory() as uow:
            match = await uow.matches.get_by_room(room_id)
            if match:
                match.state = GameState.GENERATING.value
                await uow.matches.save(match)

        await create_generation_job(
            room_id=room_id,
            topics=session.topics,
            difficulty=Difficulty.MEDIUM,
            count=count,
        )

        logger.info("game_generation_job_queued", room_id=room_id, count=count)
        return session

    async def begin_play(self, room_id: str) -> GameSession:
        """Transition the session from READY → IN_PROGRESS and record the start time.

        The caller is responsible for launching the game loop as a background
        task after this returns.

        Raises:
            ValueError: If the session does not exist or is not in READY state.
        """

        session = await self.store.get(room_id)

        if not session:
            logger.warning("game_begin_failed", room_id=room_id, reason="session_not_found")
            raise ValueError("Session not found")

        if session.state != GameState.READY:
            logger.warning(
                "game_begin_failed",
                room_id=room_id,
                reason="invalid_state",
                state=session.state.name,
            )
            raise ValueError("Game is not ready to begin")

        session.set_state(GameState.IN_PROGRESS)
        session.question_started_at = int(time.time())
        await self.store.save(session)
        logger.info("game_started", room_id=room_id, question_started_at=session.question_started_at)

        # Mirror the state change and start timestamp to the durable match record.
        async with self.uow_factory() as uow:
            match = await uow.matches.get_by_room(room_id)
            if match:
                match.state = GameState.IN_PROGRESS.value
                match.started_at = datetime.now(timezone.utc)
                await uow.matches.save(match)

        return session
