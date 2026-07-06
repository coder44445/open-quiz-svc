from __future__ import annotations
from dataclasses import asdict
from app.domain.game.state import GameState

import asyncio
from datetime import datetime, timezone

from app.core.logging import logger
from app.services.match_result import MatchResult
from app.services.game_service import GameService
from app.infrastructure.redis.session_repository import SessionRepository
from app.infrastructure.database.unit_of_work import UnitOfWork


class GameLoop:
    """
    Executes real-time game progression.
    Stateless. Redis is the source of truth.
    """

    def __init__(self, service: GameService, unit_of_work_factory: type[UnitOfWork] | None = None) -> None:
        self.service = service
        self.store = SessionRepository()
        self.uow_factory = unit_of_work_factory or UnitOfWork

    async def run(self, room_id: str) -> MatchResult | None:
        session = await self.store.get(room_id)

        if not session:
            return None

        logger.info("game_loop_started", room_id=room_id)

        while True:
            session = await self.store.get(room_id)

            if not session or session.state.name == "FINISHED":
                break

            if session.state.name != "IN_PROGRESS":
                await asyncio.sleep(0.2)
                continue

            question = session.get_current_question()

            if not question:
                session.set_state(GameState.FINISHED)
                await self.store.save(session)
                break

            logger.info(
                "question_sent",
                room_id=room_id,
                question_id=question.id,
            )

            # Persist session state and publish sync so reconnecting clients
            # can recover the current question and remaining time.
            await self.store.save(session)
            try:
                session._sync_session_state()
            except Exception:
                # avoid crashing the loop on event publish issues
                logger.exception("session_sync_failed", room_id=room_id)

            await asyncio.sleep(session.time_limit)

            session.next_question()
            await self.store.save(session)

        session = await self.store.get(room_id)

        if not session:
            return None

        result = MatchResult(
            room_id=room_id,
            leaderboard=session.get_leaderboard(),
            total_questions=len(session.questions),
        )

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
            match.leaderboard = [asdict(p) for p in session.get_leaderboard()]

        logger.info("game_finished", room_id=room_id)

        return result
