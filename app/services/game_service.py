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
import random
import asyncio
from app.infrastructure.events.event_bus import GameEventBus
from app.domain.events import GameEvent
from app.domain.event_types import EventType

event_bus = GameEventBus()


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

        # Broadcast updated player list to all connected clients
        await event_bus.publish(GameEvent(
            type=EventType.PLAYER_JOINED,
            room_id=room_id,
            payload={
                "player_id": player.id,
                "player_name": player.name,
                "players": [
                    {"id": p.id, "name": p.name, "score": p.score}
                    for p in session.players.values()
                ],
            },
        ))

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

    async def remove_player(self, room_id: str, player_id: str) -> None:
        """Remove a player from the session on disconnect and broadcast the updated list."""
        session = await self.store.get(room_id)
        if not session or player_id not in session.players:
            return

        player_name = session.players[player_id].name
        del session.players[player_id]

        # Also remove from pending topic submitters if they disconnect mid-collection
        if player_id in session.pending_topic_submitters:
            session.pending_topic_submitters.remove(player_id)

        await self.store.save(session)
        logger.info("player_removed", room_id=room_id, player_id=player_id)

        await event_bus.publish(GameEvent(
            type=EventType.PLAYER_LEFT,
            room_id=room_id,
            payload={
                "player_id": player_id,
                "player_name": player_name,
                "players": [
                    {"id": p.id, "name": p.name, "score": p.score}
                    for p in session.players.values()
                ],
            },
        ))

        # If their disconnect emptied the pending list, auto-start if we were collecting
        if (
            session.chosen_topic_submitters
            and not session.pending_topic_submitters
            and session.state == GameState.LOBBY
            and session.topics
        ):
            logger.info("pending_empty_after_disconnect_auto_starting", room_id=room_id)
            await self.start_game(room_id)


    async def add_topic(self, room_id: str, topic: str, player_id: str | None = None) -> None:
        """Append a topic to the session's topic list.

        During topic collection: each chosen player can submit exactly one topic.
        Outside of collection: topics can be added freely (legacy / admin path).
        """

        session = await self.store.get(room_id)

        if not session:
            logger.info("session_missing_for_topic_add", room_id=room_id)
            session = await self.create_session(room_id)

        # --- Enforce one-topic-per-player during collection phase ---
        if player_id and session.chosen_topic_submitters:
            if player_id not in session.pending_topic_submitters:
                # This player was either not chosen or already submitted
                logger.warning(
                    "topic_rejected_already_submitted",
                    room_id=room_id,
                    player_id=player_id,
                )
                return  # silently drop — frontend already hid the input

        topic = topic.strip()
        if not topic:
            return

        session.add_topic(topic)

        # Topic collection flow: mark player as done
        if player_id and player_id in session.pending_topic_submitters:
            session.pending_topic_submitters.remove(player_id)

        await self.store.save(session)
        logger.info(
            "topic_added",
            room_id=room_id,
            topic=topic,
            topic_count=len(session.topics),
            pending_count=len(session.pending_topic_submitters),
        )

        # If we were collecting topics and everyone submitted, auto-start
        if (
            session.chosen_topic_submitters
            and not session.pending_topic_submitters
            and session.state == GameState.LOBBY
        ):
            logger.info("all_topics_collected_auto_starting", room_id=room_id)
            await event_bus.publish(GameEvent(
                type=EventType.TOPICS_COLLECTED,
                room_id=room_id,
                payload={"pending_remaining": 0},
            ))
            try:
                await self.start_game(room_id)
            except Exception as e:
                logger.error("auto_start_failed", room_id=room_id, error=str(e))
        elif session.pending_topic_submitters:
            # Broadcast progress so host can see how many still need to submit
            await event_bus.publish(GameEvent(
                type=EventType.TOPICS_COLLECTED,
                room_id=room_id,
                payload={"pending_remaining": len(session.pending_topic_submitters)},
            ))

    async def request_topics(self, room_id: str) -> None:
        """Pick random players to submit topics, and start a 30s timeout."""
        session = await self.store.get(room_id)
        if not session or session.state != GameState.LOBBY:
            raise ValueError("Can only request topics from LOBBY")

        # Guard: don't restart collection if already in progress
        if session.chosen_topic_submitters:
            raise ValueError("Topic collection is already in progress")

        n = min(5, len(session.players))
        if n == 0:
            raise ValueError("No players to request topics from")

        chosen = random.sample(list(session.players.values()), n)
        session.chosen_topic_submitters = [p.id for p in chosen]
        session.pending_topic_submitters = [p.id for p in chosen]
        await self.store.save(session)
        
        logger.info("topics_requested", room_id=room_id, chosen_count=n)

        # Broadcast per-player topic request events
        for player in chosen:
            await event_bus.publish(GameEvent(
                type=EventType.TOPIC_REQUEST,
                room_id=room_id,
                payload={"player_id": player.id}
            ))

        # Immediately tell ALL clients how many players were chosen so the
        # host's pending count is accurate from the start (not stale/optimistic).
        await event_bus.publish(GameEvent(
            type=EventType.TOPICS_COLLECTED,
            room_id=room_id,
            payload={"pending_remaining": n},
        ))

        # Start 30s timeout task
        async def _timeout_task():
            await asyncio.sleep(30)
            current_session = await self.store.get(room_id)
            # If still waiting for topics in LOBBY, force start
            if current_session and current_session.state == GameState.LOBBY and current_session.chosen_topic_submitters:
                logger.info("topic_collection_timeout", room_id=room_id)
                await event_bus.publish(GameEvent(
                    type=EventType.TOPICS_COLLECTED,
                    room_id=room_id,
                    payload={"timeout": True}
                ))
                # Add default topic if none submitted
                if not current_session.topics:
                    await self.add_topic(room_id, "General Knowledge")
                await self.start_game(room_id)

        asyncio.create_task(_timeout_task())

    async def start_game(self, room_id: str, count: int | None = None) -> GameSession:
        """Transition the session to GENERATING and enqueue an AI question-generation job.

        Args:
            room_id: Target quiz room.
            count:   Number of questions to generate (defaults to settings.total_questions).

        Raises:
            ValueError: If the session does not exist, is not in LOBBY state,
                        or has no topics.
        """
        if count is None:
            from app.core.config import settings
            count = settings.total_questions

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

        # Notify all clients that generation is starting
        await event_bus.publish(GameEvent(
            type=EventType.GAME_STATE_CHANGED,
            room_id=room_id,
            payload={"from": GameState.LOBBY.value, "to": GameState.GENERATING.value},
        ))

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

        if session.state not in (GameState.READY, GameState.GENERATING):
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
