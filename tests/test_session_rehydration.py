import asyncio
import os

import pytest

# Ensure config can initialize during tests by providing minimal env vars
if "DATABASE_URL" not in os.environ:
    raise RuntimeError("DATABASE_URL is not set")

os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')

import sys
import types

# Provide a fake UnitOfWork module to avoid initializing real DB engines during tests
class FakeUoW:
    async def __aenter__(self):
        class Repo:
            async def get_by_room(self, room_id):
                return FakeMatch(1, state='ready')

            async def get_by_match(self, match_id):
                return [FakeQuestionRow({'id': 0, 'topic': 'x', 'text': 'q', 'options': ['a','b'], 'correct_index': 0})]

        class MatchPlayersRepo:
            async def get_by_match(self, match_id):
                from app.domain.player.model import Player
                return [FakeMatchPlayer(Player(name='alice'))]

        class AnswersRepo:
            async def get_by_match(self, match_id):
                return [FakeAnswerRow(question_id=0, player_id='alice', selected_option=0, time_taken=1.2)]

        return types.SimpleNamespace(
            matches=Repo(),
            questions=Repo(),
            match_players=MatchPlayersRepo(),
            answers=AnswersRepo(),
        )

    async def __aexit__(self, exc_type, exc, tb):
        return False


uow_module = types.ModuleType('app.infrastructure.database.unit_of_work')
uow_module.UnitOfWork = FakeUoW
sys.modules['app.infrastructure.database.unit_of_work'] = uow_module

from app.infrastructure.redis.session_repository import SessionRepository
from app.domain.question.model import Question
from app.domain.game.answer import Answer


class DummyRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return None

    async def set(self, key, value):
        self.store[key] = value


class FakeMatch:
    def __init__(self, id, state='ready'):
        self.id = id
        self.state = state


class FakeQuestionRow:
    def __init__(self, question_json):
        self.question_json = question_json


class FakeMatchPlayer:
    def __init__(self, player):
        self.player = player


class FakeAnswerRow:
    def __init__(self, question_id, player_id, selected_option, time_taken):
        self.question_id = question_id
        self.player_id = player_id
        self.selected_option = selected_option
        self.time_taken = time_taken


class FakeUoW:
    async def __aenter__(self):
        class Repo:
            async def get_by_room(self, room_id):
                return FakeMatch(1, state='ready')

            async def get_by_match(self, match_id):
                return [FakeQuestionRow({'id': 0, 'topic': 'x', 'text': 'q', 'options': ['a','b'], 'correct_index': 0})]

        class MatchPlayersRepo:
            async def get_by_match(self, match_id):
                from app.domain.player.model import Player
                return [FakeMatchPlayer(Player(name='alice'))]

        class AnswersRepo:
            async def get_by_match(self, match_id):
                return [FakeAnswerRow(question_id=0, player_id='alice', selected_option=0, time_taken=1.2)]

        return type('Ctx', (), {
            'matches': Repo(),
            'questions': Repo(),
            'match_players': MatchPlayersRepo(),
            'answers': AnswersRepo(),
        })

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_rehydrate_session(monkeypatch):
    repo = SessionRepository()
    monkeypatch.setattr(repo, 'redis', DummyRedis())

    # patch UnitOfWork used inside the repository
    from app.infrastructure.database import unit_of_work as sr
    monkeypatch.setattr(sr, 'UnitOfWork', FakeUoW)

    session = await repo.get('room-1')

    assert session is not None
    assert session.match_id == 1
    assert len(session.questions) == 1
    assert '0' in session.answers or 0 in session.answers
