import uuid
from app.ai.jobs.model import GenerationJob, JobStatus
from app.ai.jobs.repository import JobRepository
from app.core.redis import enqueue_job
from app.domain.question.difficutly import Difficulty

job_repo = JobRepository()

async def create_generation_job(
    room_id: str,
    topics: list[str],
    difficulty: Difficulty,
    count: int,
):
    job = GenerationJob(
        job_id=str(uuid.uuid4()),
        room_id=room_id,
        topics=topics,
        difficulty=difficulty,
        count=count,
        status=JobStatus.PENDING,
    )

    await job_repo.save(job)
    await enqueue_job('generate_questions', job.job_id)
    return job.job_id
