"""자료 요약·수치 추출을 필요할 때만 — 사람이 자료를 열 때, 채택할 때, 초안을 만들기 직전.

수집 단계는 원문과 기본 정보(제목·출처·날짜)만 저장하고 저가 모델로 관련성만 거른다. 비싼 모델의 추출은
아무도 보지 않을 자료에는 쓰지 않는다.
"""
from __future__ import annotations

from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs import register
from app.models import Job, Material, Project
from app.services.ledger import RunLedger

PENDING = "pending"


def pending_accepted(db: Session, project_id: str) -> list[Material]:
    return list(db.scalars(select(Material).where(Material.project_id == project_id,
                                                  Material.review_status == "accepted",
                                                  Material.extraction_status == PENDING)))


def extract_many(db: Session, project: Project, materials: Iterable[Material], job_id: str | None = None,
                 progress: Callable[[int], None] | None = None) -> dict:
    """차례로 추출한다(한 건 실패는 다음 건을 막지 않는다). 예산 초과면 그 자리에서 멈춘다."""
    from app.services.research import extract_material
    from integrations.base import ProviderError

    rows = list(materials)
    ledger = RunLedger(db, project.id, job_id)
    done = failed = 0
    for i, m in enumerate(rows, 1):
        try:
            out = extract_material(db, ledger, project, m)
        except ProviderError as exc:
            db.commit()
            if exc.code == "BUDGET_EXCEEDED":
                return {"done": done, "failed": failed + 1, "stopped": exc.message, "left": len(rows) - i}
            raise
        failed += 1 if out["errors"] else 0
        done += 0 if out["errors"] else 1
        db.commit()
        if progress:
            progress(int(i * 100 / max(1, len(rows))))
    return {"done": done, "failed": failed, "left": 0}


@register("material_extract")
def run_material_extract(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    """모두 채택 뒤: 채택됐지만 아직 추출 전인 자료의 요약·수치·문장을 만든다(장표에 들어갈 수 있게)."""
    project = db.get(Project, job.project_id)
    ids = set(job.params.get("material_ids") or [])
    rows = [m for m in pending_accepted(db, project.id) if not ids or m.id in ids]
    return extract_many(db, project, rows, job.id, progress)
