from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Match(Base):
    """
    Stores completed game metadata and results.
    """

    __tablename__ = "matches"
    __table_args__ = (
        # Speeds up both the history list query (WHERE state='finished' ORDER BY finished_at)
        # and the cleanup job (WHERE state IN (...) AND created_at < cutoff).
        Index("ix_matches_state_created_at", "state", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="lobby")

    difficulty: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, server_default=func.now())

    total_players: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
