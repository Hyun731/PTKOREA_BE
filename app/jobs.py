"""Job runner. State lives in the DB, so a closed browser does not stop work and a
reconnecting client recovers progress from GET /jobs/{id} (PRD 13).

Backends: `thread` (in-process pool, dev), `eager` (inline, tests), `celery` (worker
process, see workers/celery_app.py). Handlers are the same functions in every backend.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.errors import ApiError
from app.models import Job, new_id, utcnow

log = logging.getLogger("jobs")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job")  # research runs may overlap
HANDLERS: dict[str, Callable[[Session, Job, Callable[[int], None]], dict]] = {}


class JobFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def register(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def create_job(db: Session, project_id: str, project_version: int, kind: str, params: dict,
               idempotency_key: Optional[str] = None) -> tuple[Job, bool]:
    """Returns (job, created). The same Idempotency-Key never starts a second job."""
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == kind,
                                               Job.idempotency_key == idempotency_key))
        if existing:
            return existing, False
    job = Job(id=new_id("JOB"), project_id=project_id, project_version=project_version, kind=kind, params=params,
              idempotency_key=idempotency_key)
    db.add(job)
    db.commit()
    return job, True


def dispatch(job_id: str) -> None:
    if settings.job_backend == "celery":
        from workers.celery_app import app as celery_app
        celery_app.send_task("ptk.run_job", args=[job_id])
    elif settings.job_backend == "eager":
        run_job(job_id)
    else:
        _executor.submit(run_job, job_id)


def run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None or job.state in ("cancelled", "succeeded"):
            return
        job.state, job.started_at, job.attempts = "running", utcnow(), job.attempts + 1
        db.commit()

        def progress(pct: int):
            job.progress = max(0, min(100, pct))
            db.commit()

        try:
            result = HANDLERS[job.kind](db, job, progress)
            db.refresh(job)
            if job.state == "cancelled":
                return
            job.state, job.result, job.progress = "succeeded", result or {}, 100
        except JobFailure as exc:
            db.rollback()
            job = db.get(Job, job_id)
            job.state, job.error_code, job.error_message = "failed", exc.code, exc.message
        except ApiError as exc:
            db.rollback()
            job = db.get(Job, job_id)
            job.state, job.error_code, job.error_message = "failed", exc.code, exc.message
        except Exception as exc:  # never leak tracebacks to clients
            log.exception("job %s failed", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            job.state, job.error_code, job.error_message = "failed", "INTERNAL", f"작업 실패: {type(exc).__name__}"
        job.finished_at = utcnow()
        if job.state in ("failed", "cancelled"):
            release_items(db, job, job.error_message or "조사가 끝나지 못했습니다. 다시 실행하세요")
        db.commit()
    finally:
        db.close()


def release_items(db, job: Job, reason: str) -> None:
    """A research run that ends abnormally must not leave its items locked as 'running'."""
    if job.kind != "research_run":
        return
    from app.models import ResearchItem
    for iid in job.params.get("item_ids", []):
        item = db.get(ResearchItem, iid)
        if item is not None and item.latest_job_id == job.id and item.execution_status in ("queued", "running"):
            item.execution_status = "failed"
            item.last_result = {"status": "failed", "job_id": job.id, "at": utcnow().isoformat(),
                                "errors": [{"code": job.error_code or "JOB_ENDED", "message": reason}]}


def recover_orphans() -> int:
    """In-process jobs cannot survive a restart: mark them failed so they can be retried."""
    if settings.job_backend == "celery":
        return 0
    db = SessionLocal()
    try:
        n = 0
        for job in db.scalars(select(Job).where(Job.state.in_(("queued", "running")))):
            job.state, job.error_code = "failed", "WORKER_RESTARTED"
            job.error_message = "서버 재시작으로 중단되었습니다. 다시 실행하세요"
            job.finished_at = utcnow()
            release_items(db, job, job.error_message)
            n += 1
        # items left 'running' by a run that already ended (older data, before items were released)
        from app.models import ResearchItem
        for item in db.scalars(select(ResearchItem).where(ResearchItem.execution_status.in_(("queued", "running")))):
            owner = db.get(Job, item.latest_job_id) if item.latest_job_id else None
            if owner is None or owner.state not in ("queued", "running"):
                item.execution_status = "failed"
                item.last_result = {"status": "failed", "at": utcnow().isoformat(), "errors": [
                    {"code": "WORKER_RESTARTED", "message": "조사가 중단되었습니다. 다시 실행하세요"}]}
        db.commit()
        return n
    finally:
        db.close()
