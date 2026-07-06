import json
import asyncio
from app.ai.jobs.repository import JobRepository
from app.ai.jobs.model import JobStatus
from app.infrastructure.events.event_bus import GameEventBus
from app.domain.events import GameEvent
from app.domain.event_types import EventType
from app.ai.engine import AIEngine
from app.ai.providers.ollama import OllamaProvider
from app.infrastructure.database.unit_of_work import UnitOfWork
from app.infrastructure.database.models.question import Question as QuestionModel
from app.domain.game.state import GameState
from app.infrastructure.redis.session_repository import SessionRepository
from app import metrics


job_repo = JobRepository()
event_bus = GameEventBus()


session_store = SessionRepository()

async def generate_questions(ctx, job_id: str):
    job = await job_repo.get(job_id)

    if not job:
        return

    # JOB STARTED EVENT
    await event_bus.publish(
        GameEvent(
            type=EventType.JOB_STARTED,
            room_id=job.room_id,
            payload={"job_id": job.job_id},
        )
    )

    job.status = JobStatus.RUNNING
    await job_repo.save(job)
    metrics.mark_job_started()

    try:
        provider = OllamaProvider(model="qwen3:8b")
        engine = AIEngine(provider)

        # PROGRESS EVENT (start)
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_PROGRESS,
                room_id=job.room_id,
                payload={"job_id": job.job_id, "progress": 30},
            )
        )

        # Retry with exponential backoff for transient AI failures
        questions = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            metrics.mark_attempt()
            try:
                questions = await engine.generate_questions(
                    topics=job.topics,
                    difficulty=job.difficulty,
                    count=job.count,
                )
                break
            except Exception as e:
                await event_bus.publish(
                    GameEvent(
                        type=EventType.JOB_PROGRESS,
                        room_id=job.room_id,
                        payload={
                            "job_id": job.job_id,
                            "progress": int(30 + (attempt / max_attempts) * 40),
                            "last_error": str(e),
                        },
                    )
                )
                if attempt == max_attempts:
                    raise
                # exponential backoff
                await asyncio.sleep(2 ** attempt)

        # PROGRESS EVENT (validation done)
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_PROGRESS,
                room_id=job.room_id,
                payload={"job_id": job.job_id, "progress": 80},
            )
        )

        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(job.room_id)
            if not match:
                raise ValueError("Match record not found for generated questions")

            questions_to_save = [
                QuestionModel(
                    match_id=match.id,
                    order=index,
                    question_json=q.__dict__,
                )
                for index, q in enumerate(questions)
            ]
            await uow.questions.save_all(questions_to_save)
            match.state = GameState.READY.value
            await uow.matches.save(match)

        session = await session_store.get(job.room_id)
        if session:
            session.questions = questions
            session.set_state(GameState.READY)
            await session_store.save(session)

        await ctx["redis"].set(
            f"questions:{job.room_id}",
            json.dumps([q.__dict__ for q in questions]),
        )

        job.status = JobStatus.COMPLETED
        await job_repo.save(job)
        metrics.mark_job_completed()

        # COMPLETED EVENT
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_COMPLETED,
                room_id=job.room_id,
                payload={
                    "job_id": job.job_id,
                    "question_count": len(questions),
                },
            )
        )

    except Exception as e:
        job.status = JobStatus.FAILED
        await job_repo.save(job)
        metrics.mark_job_failed()

        # FAILED EVENT
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_FAILED,
                room_id=job.room_id,
                payload={
                    "job_id": job.job_id,
                    "error": str(e),
                },
            )
        )

class WorkerSettings:
    functions = [generate_questions]