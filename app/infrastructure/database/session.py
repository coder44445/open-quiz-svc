from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

def _normalize_database_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == 'sqlite':
        return url.replace('sqlite://', 'sqlite+aiosqlite://', 1)
    return url

_engine = create_async_engine(
    _normalize_database_url(settings.database_url),
    echo=settings.debug,
    pool_pre_ping=True,
)

_session_factory = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def create_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the application's async session factory."""

    return _session_factory


async def dispose_engine() -> None:
    """Release all database connections."""

    await _engine.dispose()