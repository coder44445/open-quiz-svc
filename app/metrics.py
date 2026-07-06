from prometheus_client import Counter

# AI worker metrics
AI_JOBS_STARTED = Counter('ai_jobs_started_total', 'Number of AI generation jobs started')
AI_JOBS_COMPLETED = Counter('ai_jobs_completed_total', 'Number of AI generation jobs completed')
AI_JOBS_FAILED = Counter('ai_jobs_failed_total', 'Number of AI generation jobs failed')
AI_JOB_ATTEMPTS = Counter('ai_job_attempts_total', 'Total AI generation attempts (including retries)')


def mark_job_started():
    AI_JOBS_STARTED.inc()


def mark_job_completed():
    AI_JOBS_COMPLETED.inc()


def mark_job_failed():
    AI_JOBS_FAILED.inc()


def mark_attempt():
    AI_JOB_ATTEMPTS.inc()
