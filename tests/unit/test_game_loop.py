import types

import pytest

from app.services.game_loop import GameLoop
from app.services.game_service import GameService
from app.domain.game.session import GameSession
from app.domain.question.model import Question
from app.domain.player.model import Player
from app.domain.game.state import GameState


class FastSleep:
    def __init__(self):
        pass

    async def __call__(self, t):
        # no-op sleep to fast-forward loop
        return None


class FakeStore:
    def __init__(self, session: GameSession):
        self._session = session

    async def get(self, room_id):
        return self._session

    async def save(self, session):
        self._session = session


class FakeUoW:
    async def __aenter__(self):
        class Matches:
            async def get_by_room(self, room_id):
                return None

            async def add(self, match):
                return None

        return types.SimpleNamespace(matches=Matches())

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_game_loop_finishes(monkeypatch):
    svc = GameService()
    loop = GameLoop(svc, unit_of_work_factory=FakeUoW)

    # create a session with two questions
    s = GameSession(room_id='r1')
    s.questions = [Question(id=0, topic='t', text='q1', options=['a'], correct_index=0),
                   Question(id=1, topic='t2', text='q2', options=['a'], correct_index=0)]
    s.players = {Player(name='alice').id: Player(name='alice')}
    s.state = GameState.IN_PROGRESS
    s.time_limit = 0  # quick loop

    # inject fake store and UoW
    monkeypatch.setattr(loop, 'store', FakeStore(s))

    # patch sleep to avoid delays
    monkeypatch.setattr('asyncio.sleep', FastSleep())

    result = await loop.run('r1')
    assert result is not None
    assert result.total_questions == 2
