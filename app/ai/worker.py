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
from app.domain.question.difficutly import Difficulty
from app.infrastructure.redis.session_repository import SessionRepository
from app.core.config import settings
from app.core.redis import get_arq_settings
from arq import cron
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

        await event_bus.publish(
            GameEvent(
                type=EventType.JOB_PROGRESS,
                room_id=job.room_id,
                payload={"job_id": job.job_id, "progress": 5},
            )
        )

        # [ARCHITECTURE INTENT: Streaming Generation]
        # Generate questions one by one and append them to the session immediately.
        # This allows the GameLoop to start executing and broadcasting the first question
        # while the rest are still being generated in the background.
        max_attempts = 3
        all_questions = []
        
        for i in range(job.count):
            topic_entry = job.topics[i % len(job.topics)]
            topic = topic_entry.get("text", "General Knowledge") if isinstance(topic_entry, dict) else topic_entry
            
            # If the topic dict has a specific difficulty, use it; otherwise fallback to the global job difficulty
            if isinstance(topic_entry, dict) and "difficulty" in topic_entry:
                try:
                    target_diff = Difficulty(topic_entry["difficulty"])
                except ValueError:
                    target_diff = job.difficulty
            else:
                target_diff = job.difficulty

            q_index = i
            q_model = None
            generated_q = None

            for attempt in range(1, max_attempts + 1):
                metrics.mark_attempt()
                attempt_start = time.perf_counter()
                log.info("generation_single_attempt_started", attempt=attempt, index=q_index, topic=topic, difficulty=target_diff.value)

                try:
                    res = await engine.generate_questions(
                        topics=[topic],
                        difficulty=target_diff,
                        count=1,
                    )
                    
                    if not res:
                        raise ValueError("No questions returned")
                        
                    generated_q = res[0]
                    generated_q.id = q_index
                        
                    elapsed_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                    log.info("generation_single_attempt_succeeded", attempt=attempt, index=q_index, elapsed_ms=elapsed_ms)
                    break

                except Exception as exc:
                    elapsed_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
                    log.warning("generation_single_attempt_failed", attempt=attempt, error=str(exc), elapsed_ms=elapsed_ms, index=q_index)

                    if attempt == max_attempts:
                        raise

                    backoff = 2 ** attempt
                    log.info("generation_backoff", seconds=backoff, attempt=attempt)
                    await asyncio.sleep(backoff)

            if not generated_q:
                raise ValueError(f"Failed to generate question {q_index} after {max_attempts} attempts")

            # Persist and broadcast this single question immediately
            async with UnitOfWork() as uow:
                match = await uow.matches.get_by_room(job.room_id)
                if not match:
                    raise ValueError("Match record not found for generated question")

                q_model = QuestionModel(
                    match_id=match.id,
                    order=q_index,
                    topic=generated_q.topic,
                    difficulty=generated_q.difficulty,
                    text=generated_q.text,
                    options=generated_q.options,
                    correct_index=generated_q.correct_index,
                )
                await uow.questions.save_all([q_model])
            
            generated_q.id = q_model.id
            all_questions.append(generated_q)

            # Update the session with the question so GameLoop can consume it
            session = await session_store.get(job.room_id)
            if not session:
                log.warning("session_not_found_during_generation")
                raise ValueError("Room is dead, stopping question generation early")
                
            connected_players = [p for p in session.players.values() if getattr(p, "is_connected", True)]
            if not connected_players:
                log.warning("abandoned_room_stopping_generation", room_id=job.room_id)
                raise ValueError("All players disconnected, stopping question generation early")
                
            session.questions = list(all_questions)  # copy current state
            
            # Transition to READY as soon as the very first question is ready
            # This allows the host to click "Begin Game" without waiting for the rest
            if len(all_questions) == 1 and session.state == GameState.GENERATING:
                session.set_state(GameState.READY)
                log.info("session_state_early_ready", room_id=job.room_id)
                
            await session_store.save(session)

            log.info("question_persisted", question_index=q_index)

            # Notify clients that one question is ready
            progress = int(10 + ((q_index + 1) / job.count) * 80)
            await event_bus.publish(
                GameEvent(
                    type=EventType.QUESTION_READY,
                    room_id=job.room_id,
                    payload={"job_id": job.job_id, "question": dataclasses.asdict(generated_q), "index": q_index}
                )
            )
            await event_bus.publish(
                GameEvent(
                    type=EventType.JOB_PROGRESS,
                    room_id=job.room_id,
                    payload={"job_id": job.job_id, "progress": progress}
                )
            )
            
            # If this is the first question, broadcast the state change to unblock the UI
            if len(all_questions) == 1:
                await event_bus.publish(GameEvent(
                    type=EventType.GAME_STATE_CHANGED,
                    room_id=job.room_id,
                    payload={"from": GameState.GENERATING.value, "to": GameState.READY.value},
                ))

        # Update the match state to READY now that all questions are generated
        async with UnitOfWork() as uow:
            match = await uow.matches.get_by_room(job.room_id)
            match.state = GameState.READY.value
            await uow.matches.save(match)

        # Update the live session in Redis so clients see READY state.
        session = await session_store.get(job.room_id)
        if session:
            session.questions = all_questions
            if session.state == GameState.GENERATING:
                session.set_state(GameState.READY)
                log.info("session_state_updated", state=GameState.READY.value)
            await session_store.save(session)
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


async def cleanup_abandoned_matches(ctx) -> None:
    """Periodic task: mark Match rows stuck in non-terminal states as 'abandoned'.

    Runs every 24 hours. Targets rooms that were created more than 3 hours ago
    but never reached 'finished' — i.e. the host abandoned the game before it
    started, or the game crashed mid-generation.

    The 3-hour window is generous enough to exclude any game still legitimately
    in progress (longest possible game: 20 questions × ~2 min each = 40 min).
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)

    async with UnitOfWork() as uow:
        stale = await uow.matches.find_stale(
            states=["lobby", "generating"],
            before=cutoff,
        )
        if not stale:
            logger.info("cleanup_no_stale_matches")
            return

        for match in stale:
            match.state = "abandoned"

    logger.info("cleanup_abandoned_matches_done", count=len(stale))
    
class WorkerSettings:
    """ARQ worker configuration.

    on_startup re-initialises the module-level Redis client inside the worker
    process.  The client is created at import time for the web process but the
    worker is a separate OS process so it needs its own initialised connection.
    """

    functions = [generate_questions]
    cron_jobs = [
        # Run daily at midnight UTC to clean up abandoned match records in the DB.
        cron(cleanup_abandoned_matches, hour=0, minute=0),
    ]
    redis_settings = get_arq_settings(settings.redis_url)
    max_tries = 1
    job_timeout = 600

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
