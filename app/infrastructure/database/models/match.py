from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Match(Base):
    """
    Stores completed game metadata and results.
    """

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="lobby")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    total_players: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    leaderboard: Mapped[dict] = mapped_column(JSON, default=list, nullable=False)
