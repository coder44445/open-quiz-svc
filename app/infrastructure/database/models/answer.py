from __future__ import annotations

from sqlalchemy import Integer, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    player_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    selected_option: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    time_taken: Mapped[float] = mapped_column(Float, nullable=False)
