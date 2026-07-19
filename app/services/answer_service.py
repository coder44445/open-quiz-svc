from __future__ import annotations

from app.core.logging import logger
from app.domain.game.answer import Answer
from app.domain.game.scoring import ScoringService
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.database.models.answer import Answer as AnswerModel
from app.infrastructure.database.models.player import Player as PlayerModel
from app.infrastructure.redis.session_repository import SessionRepository
from app.domain.events import GameEvent
from app.domain.event_types import EventType
from app.domain.game.state import GameState
from app.infrastructure.events.event_bus import GameEventBus


class AnswerService:
    def __init__(self) -> None:
        self.session_store = SessionRepository()
        self.event_bus = GameEventBus()

    async def submit_answer(
        self,
        room_id: str,
        answer: Answer,
    ) -> int:
        session = await self.session_store.get(room_id)
        if not session:
            logger.warning("answer_submission_failed", room_id=room_id, reason="session_not_found")
            raise ValueError("Session not found")

        if session.state != GameState.IN_PROGRESS:
            logger.warning("answer_submission_failed", room_id=room_id, reason="game_not_in_progress", state=session.state.name)
            raise ValueError("Game is not in progress")

        current_question = session.get_current_question()
        if not current_question or current_question.id != answer.question_id:
            logger.warning("answer_submission_failed", room_id=room_id, reason="question_mismatch", question_id=answer.question_id)
            raise ValueError("Answer does not match current question")


        accepted = session.submit_answer(answer)
        if not accepted:
            logger.warning("answer_submission_failed", room_id=room_id, reason="invalid_answer", player_id=answer.player_id)
            raise ValueError("Duplicate or invalid answer")

        score = ScoringService().score(session, answer)
        session.apply_score(answer.player_id, score)

        await self.session_store.save(session)

        import asyncio
        async def _persist_answer_to_db():
            try:
                async with UnitOfWork() as uow:
                    player = await uow.players.get(answer.player_id)
                    if not player:
                        player = PlayerModel(id=answer.player_id, name=session.players[answer.player_id].name)
                        await uow.players.save(player)

                    answer_record = AnswerModel(
                        match_id=session.match_id,
                        question_id=answer.question_id,
                        player_id=answer.player_id,
                        selected_option=answer.selected_index,
                        score=score,
                        time_taken=answer.time_taken,
                    )
                    await uow.answers.save(answer_record)
            except Exception:
                logger.exception("answer_persistence_failed", room_id=room_id, player_id=answer.player_id)

        asyncio.create_task(_persist_answer_to_db())


        await self.event_bus.publish(
            GameEvent(
                type=EventType.ANSWER_RECEIVED,
                room_id=room_id,
                payload={
                    "player_id": answer.player_id,
                    "player_name": session.players[answer.player_id].name,
                    "question_id": answer.question_id,
                    "score": score,
                    "is_correct": (answer.selected_index == current_question.correct_index),
                },
            )
        )

        logger.info(
            "answer_submitted",
            room_id=room_id,
            player_id=answer.player_id,
            question_id=answer.question_id,
            selected_index=answer.selected_index,
            correct_index=current_question.correct_index,
            selected_text=current_question.options[answer.selected_index] if 0 <= answer.selected_index < len(current_question.options) else "N/A",
            correct_text=current_question.options[current_question.correct_index] if 0 <= current_question.correct_index < len(current_question.options) else "N/A",
            is_correct=(answer.selected_index == current_question.correct_index),
            time_taken=answer.time_taken,
            time_limit=session.time_limit,
            score=score,
        )
        return score
