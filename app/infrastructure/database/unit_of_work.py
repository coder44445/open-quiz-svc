from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.infrastructure.database.session import create_session_factory
from app.repositories.match_repository import MatchRepository
from app.repositories.match_player_repository import MatchPlayerRepository
from app.repositories.question_repository import QuestionRepository
from app.repositories.answer_repository import AnswerRepository
from app.repositories.player_repository import PlayerRepository


class UnitOfWork:
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
            await self.session.rollback()
        else:
            await self.session.commit()

        await self.session.close()
        return False
