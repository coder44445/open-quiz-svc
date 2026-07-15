from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone

from app.core.logging import logger
from app.domain.events import GameEvent
from app.domain.event_types import EventType
from app.domain.game.state import GameState
from app.infrastructure.events.event_bus import GameEventBus
from app.infrastructure.redis.session_repository import SessionRepository
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.services.match_result import MatchResult


# Poll interval when waiting for all players to answer early.
_POLL_INTERVAL = 0.5


class GameLoop:
    """
    Executes real-time game progression.

    Completely decoupled from any WebSocket connection — it runs as an
    application-level background task so it survives host disconnects.

    For each question:
    1. Broadcasts the full question payload over the event bus so every
       connected client receives it simultaneously.
    2. Waits up to ``session.time_limit`` seconds, polling every
       ``_POLL_INTERVAL`` seconds to advance early if all players answered.
    3. Broadcasts the correct answer and leaderboard snapshot.
    4. Advances to the next question.
    """

    def __init__(
        self,
        service=None,  # kept for backwards compat — not used internally
        unit_of_work_factory: type[UnitOfWork] | None = None,
    ) -> None:
        self.store = SessionRepository()
        self.event_bus = GameEventBus()
        self.uow_factory = unit_of_work_factory or UnitOfWork

    async def run(self, room_id: str) -> MatchResult | None:
        session = await self.store.get(room_id)
        if not session:
            logger.warning("game_loop_no_session", room_id=room_id)
            return None

        logger.info("game_loop_started", room_id=room_id, question_count=len(session.questions))

        from app.core.config import settings
        expected_questions = settings.total_questions
        question_index = 0

        while question_index < expected_questions:
            # Reload session from Redis to pick up latest player list, scores, and newly generated questions.
            session = await self.store.get(room_id)
            if not session or session.state == GameState.FINISHED:
                break
                
            # If the next question isn't generated yet, wait for it
            if question_index >= len(session.questions):
                # Broadcast a waiting event so the UI knows we are stuck waiting for the AI
                await self.event_bus.publish(
                    GameEvent(
                        type=EventType.GAME_STATE_CHANGED,
                        room_id=room_id,
                        payload={"from": session.state.value, "to": "waiting_for_ai"}
                    )
                )
                logger.info("game_loop_waiting_for_ai", room_id=room_id, question_index=question_index)
                
                # Poll until the question is ready or we time out
                wait_time = 0
                while question_index >= len(session.questions) and wait_time < 180:
                    await asyncio.sleep(1.0)
                    wait_time += 1
                    session = await self.store.get(room_id)
                    if not session or session.state == GameState.FINISHED:
                        return None
                        
                # If we broke out of polling and still don't have the question, break out of game loop
                if question_index >= len(session.questions):
                    break

            question = session.questions[question_index]

            session.current_question_index = question_index
            import time as _time
            session.question_started_at = int(_time.time())
            await self.store.save(session)

            logger.info(
                "question_broadcasting",
                room_id=room_id,
                question_index=question_index,
                question_id=question.id,
            )

            # ── Broadcast full question to every connected client ──────────
            await self.event_bus.publish(
                GameEvent(
                    type=EventType.QUESTION_SENT,
                    room_id=room_id,
                    payload={
                        "index": question_index,
                        "total": expected_questions,
                        "time_limit": session.time_limit,
                        "question": {
                            "id": question.id,
                            "topic": question.topic,
                            "text": question.text,
                            "options": question.options,
                            # NOTE: correct_index is intentionally withheld here.
                            # It is only sent in QUESTION_RESULT below.
                        },
                    },
                )
            )

            # ── Wait: time limit OR all players answered ───────────────────
            import time as _time
            effective_time_limit = session.time_limit

            while (_time.time() - session.question_started_at) < effective_time_limit:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed = _time.time() - session.question_started_at

                # Re-read session to check latest answers
                session = await self.store.get(room_id)
                if not session:
                    return None

                if session.all_players_answered():
                    logger.info(
                        "all_players_answered_early",
                        room_id=room_id,
                        question_index=question_index,
                        elapsed=round(elapsed, 1),
                    )
                    break

                # Dynamically lower the wait time if someone disconnects
                # This gives them 20 seconds to reconnect (e.g. page refresh) without freezing the game for 60s
                if effective_time_limit > 20:
                    has_disconnected = any(not getattr(p, "is_connected", True) for p in session.players.values())
                    if has_disconnected:
                        logger.info("dropping_time_limit_for_disconnect", room_id=room_id)
                        effective_time_limit = 20

            # ── Broadcast result: reveal correct answer + leaderboard ──────
            await self.event_bus.publish(
                GameEvent(
                    type=EventType.QUESTION_RESULT,
                    room_id=room_id,
                    payload={
                        "index": question_index,
                        "correct_index": question.correct_index,
                        "leaderboard": [
                            {
                                "player_id": p.player_id,
                                "name": p.player_name,
                                "score": p.score,
                            }
                            for p in session.get_leaderboard()
                        ],
                    },
                )
            )

            logger.info(
                "question_completed",
                room_id=room_id,
                question_index=question_index,
            )
            
            # Brief pause so players can see the correct answer/leaderboard updates
            # before the next question is broadcast (or the game finishes).
            await asyncio.sleep(3.0)
            
            question_index += 1

        # ── Game finished ──────────────────────────────────────────────────
        session = await self.store.get(room_id)
        if not session:
            return None

        session.state = GameState.FINISHED
        await self.store.save(session)

        result = MatchResult(
            room_id=room_id,
            leaderboard=session.get_leaderboard(),
            total_questions=len(session.questions),
        )

        # Broadcast final leaderboard to all clients
        await self.event_bus.publish(
            GameEvent(
                type=EventType.GAME_FINISHED,
                room_id=room_id,
                payload={
                    "leaderboard": [
                        {
                            "player_id": p.player_id,
                            "name": p.player_name,
                            "score": p.score,
                        }
                        for p in result.leaderboard
                    ]
                },
            )
        )

        # Persist result to database
        async with self.uow_factory() as uow:
            match = None
            if session.match_id is not None:
                match = await uow.matches.get_by_room(room_id)

            if not match:
                from app.infrastructure.database.models.match import Match
                match = Match(room_id=room_id)
                await uow.matches.add(match)

            match.state = "finished"
            match.finished_at = datetime.now(timezone.utc)
            match.total_players = len(session.players)
            match.total_questions = len(session.questions)

        logger.info("game_finished", room_id=room_id, player_count=len(session.players))
        return result
