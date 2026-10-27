"""Celery worker (JOB_BACKEND=celery). Runs the same job handlers as the in-process runner.

    celery -A workers.celery_app worker -l info
"""
from celery import Celery

from app.config import settings

app = Celery("ptk", broker=settings.redis_url, backend=settings.redis_url)
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1


@app.task(name="ptk.run_job", bind=True, max_retries=0)
def run_job_task(self, job_id: str):
    from app.jobs import run_job
    from app.services import deck, insights, research  # noqa: F401  (registers handlers)
    run_job(job_id)
