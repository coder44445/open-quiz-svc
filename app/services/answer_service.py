from __future__ import annotations

from app.core.redis import redis
from app.domain.game.answer import Answer
from app.domain.game.scoring import ScoringService
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.database.models.answer import Answer as AnswerModel
from app.infrastructure.database.models.player import Player as PlayerModel
from app.infrastructure.redis.session_repository import SessionRepository
from app.domain.events import GameEvent
from app.domain.event_types import EventType
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
            raise ValueError("Session not found")

        if session.state != session.state.IN_PROGRESS:
            raise ValueError("Game is not in progress")

        current_question = session.get_current_question()
        if not current_question or current_question.id != answer.question_id:
            raise ValueError("Answer does not match current question")

        key = f"idempotency:answer:{room_id}:{answer.question_id}:{answer.player_id}"
        if await redis.get(key):
            raise ValueError("Duplicate answer")

        accepted = session.submit_answer(answer)
        if not accepted:
            raise ValueError("Duplicate or invalid answer")

        score = ScoringService().score(session, answer)
        session.apply_score(answer.player_id, score)

        await self.session_store.save(session)

        async with UnitOfWork() as uow:
            player = await uow.players.get(answer.player_id)
            if not player:
                player = PlayerModel(id=answer.player_id, name=session.players[answer.player_id].name)
                await uow.players.save(player)

            answer_record = AnswerModel(
                question_id=answer.question_id,
                player_id=answer.player_id,
                selected_option=answer.selected_index,
                score=score,
                time_taken=answer.time_taken,
            )
            await uow.answers.save(answer_record)

        await redis.set(key, "1", ex=60 * 5)

        await self.event_bus.publish(
            GameEvent(
                type=EventType.ANSWER_RECEIVED,
                room_id=room_id,
                payload={
                    "player_id": answer.player_id,
                    "question_id": answer.question_id,
                    "score": score,
                },
            )
        )

        return score
