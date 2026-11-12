"""브랜드 진단(P5-1) — 초안 화면 "진단" 탭: 보기, 다시 쓰기, 주장 빼기·문장 고치기, 되돌리기.

모든 변경은 덮어쓰지 않고 새 버전으로 남는다(사람이 바꾼 버전은 덱을 다시 만들어도 AI가 덮어쓰지 않는다).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError, not_found
from app.routers.projects import actor, get_project
from app.services.audit import audit
from core.schemas.diagnosis import KIND_LABEL, DiagnosisVersion
from core.schemas.slidespec import Headline, Paragraph

router = APIRouter()


def _version_out(v: DiagnosisVersion) -> dict:
    return {"version": v.version, "origin": v.origin, "by": v.by, "instruction": v.instruction,
            "created_at": v.created_at, "dropped": len(v.dropped)}


def _brand_out(db: Session, p, brand) -> dict:
    from app.services import diagnosis
    active, vs = diagnosis.versions(p, brand.id)
    current = next((v for v in vs if v.version == active), None)
    return {"brand_id": brand.id, "brand_name": brand.name, "active": active,
            "stale": diagnosis.is_stale(db, p, brand.id, current) if current else False,
            "data": current.data.model_dump(mode="json") if current else None,
            "dropped": current.dropped if current else [],
            "claim_labels": {c.id: KIND_LABEL[c.kind] for c in current.data.claims} if current else {},
            "versions": [_version_out(v) for v in reversed(vs)]}


def _brand(p, brand_id: str):
    from app.services.inputs import core_project
    try:
        return core_project(p).brand(brand_id)
    except KeyError:
        raise not_found("브랜드")


@router.get("/projects/{project_id}/diagnosis")
def read_diagnosis(project_id: str, db: Session = Depends(get_db)):
    """자사 브랜드마다 활성 진단과 버전 목록(최신 먼저). 아직 쓴 적 없는 브랜드는 data가 비어 있다."""
    from app.services.inputs import core_project
    p = get_project(db, project_id)
    return [_brand_out(db, p, b) for b in core_project(p).brands]


class RewriteIn(BaseModel):
    brand_id: str
    instruction: str = Field(default="", max_length=400)


@router.post("/projects/{project_id}/diagnosis")
def rewrite_diagnosis(project_id: str, body: RewriteIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    """다시 쓰기: 지금 채택된 자료로 그 브랜드의 진단을 새 버전으로 쓴다(요청 문장을 덧붙일 수 있음)."""
    from app.services import diagnosis
    from integrations.base import ProviderError

    p = get_project(db, project_id)
    brand = _brand(p, body.brand_id)
    if not diagnosis.ai_ready():
        raise ApiError(503, "PROVIDER_NOT_CONFIGURED", "AI 키가 설정되지 않았습니다", ".env의 ANTHROPIC_API_KEY를 확인하세요")
    try:
        v = diagnosis.generate(db, p, brand.id, body.instruction, "rewrite", by=who)
    except ValueError as exc:
        raise ApiError(409, "NO_FACTS", str(exc), "자료 확인에서 수치 자료를 채택하세요")
    except ProviderError as exc:
        raise ApiError(502, exc.code, f"AI 응답을 받지 못했습니다: {exc.message}", "잠시 뒤 다시 시도하세요")
    audit(db, project_id, "project", project_id, "diagnosis",
          after={"brand_id": brand.id, "instruction": body.instruction, "dropped": v.dropped}, actor=who)
    db.commit()
    return _brand_out(db, p, brand)


class ClaimEditIn(BaseModel):
    excluded: Optional[bool] = None  # 빼기(True) / 다시 넣기(False)
    claim: Optional[list[Paragraph]] = None  # 문장 고치기: 주장 한 줄
    evidence: Optional[list[Paragraph]] = Field(default=None, max_length=2)  # 근거 1~2줄


@router.patch("/projects/{project_id}/diagnosis/{brand_id}/claims/{claim_id}")
def edit_claim(project_id: str, brand_id: str, claim_id: str, body: ClaimEditIn, db: Session = Depends(get_db),
               who: str = Depends(actor)):
    """주장 하나를 빼거나 문장을 고친다. 숫자는 원래처럼 수치(fact) 조각으로만 둘 수 있다."""
    from app.services import diagnosis
    from app.services.insights import check_headline

    p = get_project(db, project_id)
    brand = _brand(p, brand_id)
    current = diagnosis.active_version(p, brand.id)
    if current is None:
        raise not_found("진단")
    claims = list(current.data.claims)
    i = next((k for k, c in enumerate(claims) if c.id == claim_id), None)
    if i is None:
        raise not_found("주장")
    c = claims[i]
    update: dict = {}
    if body.excluded is not None:
        update["excluded"] = body.excluded
    if body.claim is not None or body.evidence is not None:
        pi = diagnosis.planner_input(db, p, brand.id)
        head = Headline(claim=body.claim if body.claim is not None else c.claim,
                        evidence=body.evidence if body.evidence is not None else c.evidence)
        try:
            head = diagnosis.refresh_headline(head, pi)
        except KeyError as exc:
            raise ApiError(422, "UNKNOWN_FACT", f"지금 채택 자료에 없는 수치입니다: {exc.args[0]}",
                           "수치는 진단에 있던 것만 쓸 수 있습니다")
        errors = check_headline(head, pi.self_names)
        if errors:
            raise ApiError(422, "CLAIM_RULES", "; ".join(errors[:3]), "문장을 고쳐 다시 저장하세요")
        update.update({"claim": head.claim, "evidence": head.evidence, "edited": True})
    if not update:
        raise ApiError(422, "NOTHING_TO_CHANGE", "바꿀 내용이 없습니다", "빼기 또는 문장 고치기를 보내세요")
    claims[i] = c.model_copy(update=update)
    data = current.data.model_copy(update={"claims": claims})
    diagnosis.save_version(p, brand.id, current.model_copy(update={
        "data": data, "origin": "edit", "by": who, "created_at": None, "dropped": []}))
    audit(db, project_id, "project", project_id, "diagnosis_edit",
          after={"brand_id": brand.id, "claim_id": claim_id, **{k: v for k, v in update.items() if k == "excluded"}},
          actor=who)
    db.commit()
    return _brand_out(db, p, brand)


@router.post("/projects/{project_id}/diagnosis/{brand_id}/versions/{version}/activate")
def restore_version(project_id: str, brand_id: str, version: int, db: Session = Depends(get_db),
                    who: str = Depends(actor)):
    """되돌리기: 고른 버전을 새 버전으로 다시 쓴다(사람이 고른 것이라 덱을 다시 만들어도 유지)."""
    from app.services import diagnosis

    p = get_project(db, project_id)
    brand = _brand(p, brand_id)
    _, vs = diagnosis.versions(p, brand.id)
    old = next((v for v in vs if v.version == version), None)
    if old is None:
        raise not_found("진단 버전")
    diagnosis.save_version(p, brand.id, old.model_copy(update={"origin": "restore", "by": who, "created_at": None}))
    audit(db, project_id, "project", project_id, "diagnosis_restore", after={"brand_id": brand.id, "version": version},
          actor=who)
    db.commit()
    return _brand_out(db, p, brand)
