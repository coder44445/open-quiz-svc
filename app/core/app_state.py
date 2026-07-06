from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(slots=True)
class AppState:
    """Shared application resources."""

    redis: Redis
    session_factory: async_sessionmaker[AsyncSession]