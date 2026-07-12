from __future__ import annotations

import asyncio
import json
import time
import dataclasses

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
from app.core.redis import get_arq_settings
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
                payload={"job_id": job.job_id, "progress": 10},
            )
        )

        all_questions = []
        max_attempts = 3

        # Generate questions one by one for streaming UX.
        for i in range(job.count):
            topic = job.topics[i % len(job.topics)]
            question = None
            
            for attempt in range(1, max_attempts + 1):
                metrics.mark_attempt()
                attempt_start = time.perf_counter()
                log.info("generation_attempt_started", attempt=attempt, question_index=i, topic=topic)

                try:
                    qs = await engine.generate_questions(
                        topics=[topic],
                        difficulty=job.difficulty,
                        count=1,
                    )
                    question = qs[0]
                    # Update ID to match the overall job sequence index (i)
                    question.id = i
                    elapsed_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                    log.info(
                        "generation_attempt_succeeded",
                        attempt=attempt,
                        question_index=i,
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
                        question_index=i,
                    )

                    if attempt == max_attempts:
                        raise

                    backoff = 2 ** attempt
                    log.info("generation_backoff", seconds=backoff, attempt=attempt)
                    await asyncio.sleep(backoff)

            if not question:
                raise ValueError(f"Failed to generate question {i+1} after {max_attempts} attempts")

            all_questions.append(question)

            # Persist this specific question immediately
            async with UnitOfWork() as uow:
                match = await uow.matches.get_by_room(job.room_id)
                if not match:
                    raise ValueError("Match record not found for generated questions")

                q_model = QuestionModel(
                    match_id=match.id,
                    order=i,
                    question_json=dataclasses.asdict(question),
                )
                await uow.questions.save_all([q_model])
            
            log.info("question_persisted", question_index=i)

            # Notify clients that one question is ready
            progress = int(10 + ((i + 1) / job.count) * 80)
            await event_bus.publish(
                GameEvent(
                    type=EventType.QUESTION_READY,
                    room_id=job.room_id,
                    payload={"job_id": job.job_id, "question": dataclasses.asdict(question), "index": i}
                )
            )
            await event_bus.publish(
                GameEvent(
                    type=EventType.JOB_PROGRESS,
                    room_id=job.room_id,
                    payload={"job_id": job.job_id, "progress": progress}
                )
            )

        # Update the match state to READY now that all questions are generated
        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(job.room_id)
            match.state = GameState.READY.value
            await uow.matches.save(match)

        # Update the live session in Redis so clients see READY state.
        session = await session_store.get(job.room_id)
        if session:
            session.questions = all_questions
            session.set_state(GameState.READY)
            await session_store.save(session)
            log.info("session_state_updated", state=GameState.READY.value)
        else:
            log.warning("session_not_found_after_generation")

        # Cache raw question JSON for fast access by clients.
        await ctx["redis"].set(
            f"questions:{job.room_id}",
            json.dumps([dataclasses.asdict(q) for q in all_questions]),
        )

        job.status = JobStatus.COMPLETED
        await job_repo.save(job)
        metrics.mark_job_completed()

        log.info("question_generation_completed", question_count=len(all_questions))

        # Notify clients that questions are ready.
        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_COMPLETED,
                room_id=job.room_id,
                payload={
                    "job_id": job.job_id,
                    "question_count": len(all_questions),
                },
            )
        )

    except (Exception, asyncio.CancelledError) as exc:
        is_cancel = isinstance(exc, asyncio.CancelledError)
        error_msg = "Job timed out" if is_cancel else str(exc)
        log.exception("question_generation_failed", error=error_msg)

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
                    "error": error_msg,
                },
            )
        )
        if is_cancel:
            raise


class WorkerSettings:
    """ARQ worker configuration.

    on_startup re-initialises the module-level Redis client inside the worker
    process.  The client is created at import time for the web process but the
    worker is a separate OS process so it needs its own initialised connection.
    """

    functions = [generate_questions]
    redis_settings = get_arq_settings(settings.redis_url)

    @staticmethod
    async def on_startup(ctx: dict) -> None:
        """Initialise shared resources inside the ARQ worker process."""
        import app.core.redis as redis_module
        from redis.asyncio import Redis

        # Re-create the module-level redis singleton for this process.
        redis_module.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("arq_worker_started", redis_url=settings.redis_url)

    @staticmethod
    async def on_shutdown(ctx: dict) -> None:
        """Clean up shared resources when the worker shuts down."""
        import app.core.redis as redis_module
        try:
            await redis_module.redis.aclose()
            logger.info("arq_worker_redis_closed")
        except Exception:
            logger.warning("arq_worker_redis_close_failed")