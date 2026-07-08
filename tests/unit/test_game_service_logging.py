import types

import pytest

from app.services.game_service import GameService


class FakeStore:
    def __init__(self) -> None:
        self.saved = None

    async def save(self, session) -> None:
        self.saved = session


class FakeUoW:
    async def __aenter__(self):
        # matches.add must be an awaitable coroutine because game_service awaits it.
        async def _async_noop(match):
            pass

        return types.SimpleNamespace(matches=types.SimpleNamespace(add=_async_noop))

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_session_emits_lifecycle_log(monkeypatch):
    captured = []

    class CaptureLogger:
        def info(self, event, **kwargs):
            captured.append((event, kwargs))

    monkeypatch.setattr("app.services.game_service.logger", CaptureLogger())

    service = GameService(unit_of_work_factory=lambda: FakeUoW())
    service.store = FakeStore()

    await service.create_session("room-1")

    assert any(event == "session_created" for event, _ in captured)
