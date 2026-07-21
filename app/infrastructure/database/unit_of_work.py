from __future__ import annotations

import structlog


from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.infrastructure.database.session import create_session_factory
from app.repositories.match_repository import MatchRepository
from app.repositories.match_player_repository import MatchPlayerRepository
from app.repositories.question_repository import QuestionRepository
from app.repositories.answer_repository import AnswerRepository
from app.repositories.player_repository import PlayerRepository

logger = structlog.get_logger(__name__)


class UnitOfWork:
    """Coordinates a single database transaction across multiple repositories.

    Usage::

        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(room_id)
            ...  # mutate entities
        # commit happens automatically on __aexit__ if no exception was raised.
        # rollback happens automatically if an exception propagates.

    A custom session_factory can be injected for testing.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self.session_factory = session_factory or create_session_factory()
        self.session: AsyncSession | None = None
        self.matches: MatchRepository | None = None
        self.match_players: MatchPlayerRepository | None = None
        self.questions: QuestionRepository | None = None
        self.answers: AnswerRepository | None = None
        self.players: PlayerRepository | None = None

    async def __aenter__(self) -> UnitOfWork:
        self.session = self.session_factory()
        self.matches = MatchRepository(self.session)
        self.match_players = MatchPlayerRepository(self.session)
        self.questions = QuestionRepository(self.session)
        self.answers = AnswerRepository(self.session)
        self.players = PlayerRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        assert self.session is not None

        if exc:
            # Log the rollback so unexpected DB failures surface in the logs.
            logger.warning(
                "database_transaction_rollback",
                exc_type=exc_type.__name__ if exc_type else None,
                error=str(exc) if exc else None,
            )
            await self.session.rollback()
        else:
            await self.session.commit()

        await self.session.close()

        # Return False so exceptions always propagate to the caller.
        return False
