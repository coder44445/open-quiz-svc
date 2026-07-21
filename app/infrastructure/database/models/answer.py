from __future__ import annotations

from sqlalchemy import Integer, Float, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.infrastructure.database.models.match import Match
    from app.infrastructure.database.models.question import Question
    from app.infrastructure.database.models.player import Player


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint('question_id', 'player_id', name='uq_player_question_answer'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True, nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True, nullable=False)
    selected_option: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    time_taken: Mapped[float] = mapped_column(Float, nullable=False)

    match: Mapped["Match"] = relationship("Match")
    question: Mapped["Question"] = relationship("Question")
    player: Mapped["Player"] = relationship("Player")
