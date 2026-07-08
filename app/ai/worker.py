from __future__ import annotations

import json
import time

import structlog

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
from app.core.config import settings
from app import metrics


job_repo = JobRepository()
event_bus = GameEventBus()
session_store = SessionRepository()

logger = structlog.get_logger(__name__)


async def generate_questions(ctx, job_id: str) -> None:
    """ARQ worker task: generate quiz questions for a room using the configured AI provider.

    Lifecycle:
      1. Load job from Redis; bail early if it no longer exists.
      2. Mark job as RUNNING and publish a JOB_STARTED event.
      3. Retry AI generation up to 3 times with exponential back-off.
      4. Persist generated questions to the database and update session state.
      5. Mark job COMPLETED and publish JOB_COMPLETED event.
      If any step raises an unrecoverable error, mark the job FAILED and
      publish JOB_FAILED so connected clients are notified immediately.

    Args:
        ctx:    ARQ worker context dict (contains the shared Redis connection).
        job_id: ID of the GenerationJob stored in Redis.
    """

    log = logger.bind(job_id=job_id)
    log.info("worker_task_started")

    job = await job_repo.get(job_id)

    if not job:
        log.warning("worker_job_not_found")
        return

    log = log.bind(room_id=job.room_id)

    # Notify clients that generation has begun.
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

    log.info(
        "question_generation_started",
        topics=job.topics,
        difficulty=job.difficulty.value,
        count=job.count,
    )

    try:
        provider = OllamaProvider(model=settings.ollama_model)
        engine = AIEngine(provider)

        # Notify clients that the AI pipeline is active.
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_PROGRESS,
                room_id=job.room_id,
                payload={"job_id": job.job_id, "progress": 30},
            )
        )

        # Retry with exponential back-off for transient AI failures.
        questions = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            metrics.mark_attempt()
            attempt_start = time.perf_counter()

            log.info("generation_attempt_started", attempt=attempt, max_attempts=max_attempts)

            try:
                questions = await engine.generate_questions(
                    topics=job.topics,
                    difficulty=job.difficulty,
                    count=job.count,
                )
                elapsed_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                log.info(
                    "generation_attempt_succeeded",
                    attempt=attempt,
                    question_count=len(questions),
                    elapsed_ms=elapsed_ms,
                )
                break

            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                log.warning(
                    "generation_attempt_failed",
                    attempt=attempt,
                    error=str(exc),
                    elapsed_ms=elapsed_ms,
                    will_retry=attempt < max_attempts,
                )

                await event_bus.publish(
                    GameEvent(
                        type=EventType.JOB_PROGRESS,
                        room_id=job.room_id,
                        payload={
                            "job_id": job.job_id,
                            "progress": int(30 + (attempt / max_attempts) * 40),
                            "last_error": str(exc),
                        },
                    )
                )

                if attempt == max_attempts:
                    # All retries exhausted — let the outer except handle it.
                    raise

                # Exponential back-off: 2 s, 4 s, …
                backoff = 2 ** attempt
                log.info("generation_backoff", seconds=backoff, attempt=attempt)
                import asyncio
                await asyncio.sleep(backoff)

        # Publish progress: validation complete.
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_PROGRESS,
                room_id=job.room_id,
                payload={"job_id": job.job_id, "progress": 80},
            )
        )

        # Persist questions and update match state in the database.
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

        log.info("questions_persisted", question_count=len(questions))

        # Update the live session in Redis so clients see READY state.
        session = await session_store.get(job.room_id)
        if session:
            session.questions = questions
            session.set_state(GameState.READY)
            await session_store.save(session)
            log.info("session_state_updated", state=GameState.READY.value)
        else:
            log.warning("session_not_found_after_generation")

        # Cache raw question JSON for fast access by clients.
        await ctx["redis"].set(
            f"questions:{job.room_id}",
            json.dumps([q.__dict__ for q in questions]),
        )

        job.status = JobStatus.COMPLETED
        await job_repo.save(job)
        metrics.mark_job_completed()

        log.info("question_generation_completed", question_count=len(questions))

        # Notify clients that questions are ready.
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

    except Exception as exc:
        log.exception("question_generation_failed", error=str(exc))

        job.status = JobStatus.FAILED
        await job_repo.save(job)
        metrics.mark_job_failed()

        # Notify clients immediately so they are not left waiting.
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_FAILED,
                room_id=job.room_id,
                payload={
                    "job_id": job.job_id,
                    "error": str(exc),
                },
            )
        )


class WorkerSettings:
    functions = [generate_questions]