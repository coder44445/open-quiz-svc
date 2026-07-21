import types
import pytest

from app.services.game_service import GameService
from app.domain.player.model import Player


class DummyStore:
    def __init__(self):
        self.saved = None

    async def get(self, room_id):
        return None

    async def save(self, session):
        self.saved = session


class FakeUoW:
    async def __aenter__(self):
        class Matches:
            async def add(self, match):
                match.id = 42

        class Players:
            async def get(self, _):
                return None

            async def save(self, *a, **k):
                return None

        class MatchPlayers:
            async def get_by_match_and_player(self, *args, **kwargs):
                return None

            async def add(self, *a, **k):
                return None

        return types.SimpleNamespace(
            matches=Matches(),
            players=Players(),
            match_players=MatchPlayers(),
        )

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_session():
    svc = GameService(unit_of_work_factory=FakeUoW)

    # replace store with dummy
    svc.store = DummyStore()

    session = await svc.create_session('room-x')

    assert session.match_id == 42
    assert svc.store.saved is session

@pytest.mark.asyncio
async def test_add_topic_and_add_player():
    class Repo:
        async def get(self, _):
            return None

        async def save(self, *a, **k):
            return None

        async def add(self, *a, **k):
            return None

    class MatchPlayersRepo:
        async def get(self, _):
            return None

        async def save(self, *a, **k):
            return None

        async def get_by_match_and_player(self, *a, **k):
            return None

        async def add(self, *a, **k):
            return None

    class FakeU:
        async def __aenter__(self):
            return types.SimpleNamespace(
                players=Repo(),
                match_players=MatchPlayersRepo(),
                matches=types.SimpleNamespace(add=self.add_match),
            )

        async def add_match(self, match):
            match.id = 42

        async def __aexit__(self, exc_type, exc, tb):
            return False

    svc = GameService(unit_of_work_factory=FakeU)
    svc.store = DummyStore()

    with pytest.raises(ValueError):
        await svc.add_topic('r1', 'history', 'medium')

    player = Player(name='bob')
    with pytest.raises(ValueError):
        await svc.add_player('r1', player)
