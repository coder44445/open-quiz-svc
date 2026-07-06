import json
from app.core.redis import redis
from app.ai.jobs.model import GenerationJob, JobStatus
from app.domain.question.difficutly import Difficulty


class JobRepository:

    PREFIX = "job:"

    async def save(self, job: GenerationJob) -> None:
        await redis.set(
            self.PREFIX + job.job_id,
            json.dumps(
                {
                    "job_id": job.job_id,
                    "room_id": job.room_id,
                    "topics": job.topics,
                    "difficulty": job.difficulty.value,
                    "count": job.count,
                    "status": job.status.value,
                }
            ),
        )

    async def get(self, job_id: str) -> GenerationJob | None:
        data = await redis.get(self.PREFIX + job_id)

        if not data:
            return None

        raw = json.loads(data)

        return GenerationJob(
            job_id=raw["job_id"],
            room_id=raw["room_id"],
            topics=raw["topics"],
            difficulty=Difficulty(raw["difficulty"]),
            count=raw["count"],
            status=JobStatus(raw["status"]),
        )
