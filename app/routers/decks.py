"""Slide plan, deck builds, previews and exports (PRD 4 팩트북 출력, 11, 12; E06, Q01, Q02, X01)."""
from __future__ import annotations

import json
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError, not_found
from app.jobs import create_job, dispatch
from app.models import Deck, Export, Job, new_id, utcnow
from app.routers.projects import actor, get_project
from app.services.audit import audit
from app.services.deck import current_fingerprint, next_deck_version
from app.services.inputs import load_inputs
from app.storage import get_storage
from core.composition.build import build_deck
from core.quality.qc import run_qc, self_brand_names

router = APIRouter()


@router.get("/projects/{project_id}/slide-plan")
def slide_plan(project_id: str, db: Session = Depends(get_db)):
    """Dry-run composition: planned vs generatable slots and current QC, without rendering."""
    p = get_project(db, project_id)
    result = build_deck(load_inputs(db, p))
    qc = run_qc(result.deck, result.metrics.registry, lambda aid: result.assets.get(aid), self_brand_names(p.config))
    return {
        "plan": [s.model_dump() for s in result.deck.plan],
        "counts": result.deck.counts(),
        "pages": [{"slide_id": s.slide_id, "title": s.title, "page_role": s.page_role, "section_id": s.section_id,
                   "needs_review": s.needs_review} for s in result.deck.slides],
        "qc": qc.to_dict(),
        "findings": [{"id": f.id, "rule_id": f.rule_id, "brand_id": f.brand_id, "strength": str(f.strength),
                      "expression": f.allowed_expression} for f in result.findings],
        "metric_issues": [i.__dict__ for i in result.metrics.issues],
        "synthetic_data": result.deck.synthetic_data,
        "fingerprint": result.deck.input_fingerprint,
    }


class OmitIn(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


@router.put("/projects/{project_id}/slot-omissions/{slot_id}")
def omit_slot(project_id: str, slot_id: str, body: OmitIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    p = get_project(db, project_id)
    p.omitted_slots = {**(p.omitted_slots or {}), slot_id: {"reason": body.reason, "by": who, "at": utcnow().isoformat()}}
    audit(db, project_id, "slot", slot_id, "omit", reason=body.reason, actor=who)
    db.commit()
    return {"omitted_slots": p.omitted_slots}


@router.delete("/projects/{project_id}/slot-omissions/{slot_id}")
def restore_slot(project_id: str, slot_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    p = get_project(db, project_id)
    p.omitted_slots = {k: v for k, v in (p.omitted_slots or {}).items() if k != slot_id}
    audit(db, project_id, "slot", slot_id, "restore", actor=who)
    db.commit()
    return {"omitted_slots": p.omitted_slots}


JOB_STALE_SECONDS = 600


def _is_stuck(job: Job) -> bool:
    started = job.started_at or job.created_at
    if started.tzinfo is None:  # SQLite returns naive UTC
        started = started.replace(tzinfo=timezone.utc)
    return (utcnow() - started).total_seconds() > JOB_STALE_SECONDS


def job_out(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "state": j.state, "progress": j.progress, "attempts": j.attempts,
            "result": j.result, "error_code": j.error_code, "error_message": j.error_message, "usage": j.usage,
            "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at}


@router.post("/projects/{project_id}/deck-builds", status_code=202)
def start_build(project_id: str, db: Session = Depends(get_db), who: str = Depends(actor),
                idempotency_key: Optional[str] = Header(default=None)):
    p = get_project(db, project_id)
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "deck_build",
                                          Job.state.in_(("queued", "running"))))
    if running and _is_stuck(running):
        # A lost worker message must not block rebuilds forever.
        running.state, running.error_code, running.finished_at = "failed", "JOB_TIMEOUT", utcnow()
        running.error_message = "작업이 제한 시간 안에 끝나지 않았습니다. 다시 실행합니다"
        deck = db.get(Deck, running.params.get("deck_id"))
        if deck and deck.status == "building":
            deck.status = "failed"
        db.commit()
        running = None
    if running:
        return {"job": job_out(running), "deck_id": running.params.get("deck_id"), "reused": True}
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "deck_build",
                                               Job.idempotency_key == idempotency_key))
        if existing:
            return {"job": job_out(existing), "deck_id": existing.params.get("deck_id"), "reused": True}
    deck = Deck(id=new_id("DECK"), project_id=project_id, version=next_deck_version(db, project_id), status="building")
    db.add(deck)
    db.flush()
    job, _ = create_job(db, project_id, p.version, "deck_build", {"deck_id": deck.id}, idempotency_key)
    deck.job_id = job.id
    audit(db, project_id, "deck", deck.id, "build", actor=who)
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return {"job": job_out(job), "deck_id": deck.id, "reused": False}


def deck_out(db: Session, d: Deck, include_spec: bool = True) -> dict:
    p = get_project(db, d.project_id)
    stale = d.status == "ready" and d.fingerprint != current_fingerprint(db, p)
    out = {"id": d.id, "version": d.version, "status": d.status, "qc": d.qc, "render_status": d.render_status,
           "render_message": d.render_message, "pages": len(d.preview_keys or []), "job_id": d.job_id,
           "created_at": d.created_at, "stale": stale, "fingerprint": d.fingerprint}
    if include_spec:
        out["spec"] = d.spec
    return out


@router.get("/projects/{project_id}/decks")
def list_decks(project_id: str, db: Session = Depends(get_db)):
    get_project(db, project_id)
    decks = db.scalars(select(Deck).where(Deck.project_id == project_id).order_by(Deck.version.desc()).limit(20))
    return [deck_out(db, d, include_spec=False) for d in decks]


def get_deck(db: Session, deck_id: str) -> Deck:
    d = db.get(Deck, deck_id)
    if d is None:
        raise not_found("덱")
    return d


@router.get("/decks/{deck_id}")
def read_deck(deck_id: str, db: Session = Depends(get_db)):
    return deck_out(db, get_deck(db, deck_id))


@router.get("/decks/{deck_id}/preview/{page}")
def deck_preview(deck_id: str, page: int, db: Session = Depends(get_db)):
    d = get_deck(db, deck_id)
    if page < 1 or page > len(d.preview_keys or []):
        raise not_found("미리보기 페이지")
    return FileResponse(get_storage().path(d.preview_keys[page - 1]), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/decks/{deck_id}/exports", status_code=202)
def start_export(deck_id: str, db: Session = Depends(get_db), who: str = Depends(actor),
                 idempotency_key: Optional[str] = Header(default=None)):
    d = get_deck(db, deck_id)
    p = get_project(db, d.project_id)
    if d.status != "ready":
        raise ApiError(409, "INVALID_STATE", "덱 생성이 끝나지 않았습니다")
    if d.fingerprint != current_fingerprint(db, p):
        raise ApiError(409, "STALE_VERSION", "덱 생성 이후 자료·검토 상태가 바뀌었습니다", "초안을 다시 생성한 뒤 내보내세요")
    if d.qc and d.qc.get("blocks"):
        raise ApiError(409, "QC_BLOCKED", f"QC 차단 {d.qc['blocks']}건이 있어 내보낼 수 없습니다", "출력 화면의 차단 항목을 해결하세요",
                       [i for i in d.qc["issues"] if i["severity"] == "block"])
    if d.render_status != "ok":
        raise ApiError(409, "RENDER_FAILED", "실제 PPTX 렌더 미리보기가 없어 확정 출력을 막았습니다",
                       "렌더러(RENDER_BACKEND) 설정을 확인한 뒤 다시 생성하세요")
    job, created = create_job(db, p.id, p.version, "export", {"deck_id": d.id}, idempotency_key)
    if created:
        audit(db, p.id, "deck", d.id, "export", actor=who)
        db.commit()
        dispatch(job.id)
        db.refresh(job)
    return {"job": job_out(job)}


def export_out(e: Export) -> dict:
    return {"id": e.id, "deck_id": e.deck_id, "deck_version": e.deck_version, "qc": {"blocks": e.qc["blocks"], "warns": e.qc["warns"]},
            "files": sorted(e.manifest), "generated_at": e.generated_at}


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: str, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return [export_out(e) for e in db.scalars(select(Export).where(Export.project_id == project_id)
                                              .order_by(Export.generated_at.desc()))]


@router.get("/exports/{export_id}/files/{name}")
def export_file(export_id: str, name: str, db: Session = Depends(get_db)):
    e = db.get(Export, export_id)
    if e is None or name not in e.manifest:
        raise not_found("출력 파일")
    media = {"pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "csv": "text/csv",
             "json": "application/json"}[name.rsplit(".", 1)[-1]]
    p = get_project(db, e.project_id)
    download = ({"report.pptx": f"{p.name}_v{e.deck_version}.pptx",
                "report_light.pptx": f"{p.name}_v{e.deck_version}_경량.pptx"}).get(name, name)
    return FileResponse(get_storage().path(e.manifest[name]), media_type=media, filename=download)


@router.get("/jobs/{job_id}")
def read_job(job_id: str, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise not_found("작업")
    return job_out(j)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    j = db.get(Job, job_id)
    if j is None:
        raise not_found("작업")
    if j.state in ("queued", "running"):
        from app.jobs import release_items
        j.state, j.finished_at = "cancelled", utcnow()
        release_items(db, j, "조사를 취소했습니다")
        audit(db, j.project_id, "job", j.id, "cancel", actor=who)
        db.commit()
    return job_out(j)


# ------------------------------------------------------------------ AI lead proposals (W01, W02)

class ProposalsIn(BaseModel):
    slide_ids: Optional[list[str]] = None


@router.post("/projects/{project_id}/insight-proposals", status_code=202)
def start_proposals(project_id: str, body: ProposalsIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    from app.config import settings
    from app.services.ledger import run_budget_usd

    p = get_project(db, project_id)
    if not settings.provider_configured("anthropic"):
        raise ApiError(503, "PROVIDER_NOT_CONFIGURED", "Anthropic 키·모델이 설정되지 않았습니다", ".env의 ANTHROPIC_API_KEY·ANTHROPIC_MODEL을 확인하세요")
    if run_budget_usd() <= 0:
        raise ApiError(409, "BUDGET_EXCEEDED", "실행 예산(RUN_BUDGET_USD)이 설정되지 않았습니다")
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "insight_proposals",
                                          Job.state.in_(("queued", "running"))))
    if running:
        return {"job": job_out(running), "reused": True}
    job, _ = create_job(db, project_id, p.version, "insight_proposals", {"slide_ids": body.slide_ids})
    audit(db, project_id, "insight_proposals", job.id, "start", actor=who)
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return {"job": job_out(job), "reused": False}


def proposal_out(lp) -> dict:
    return {"id": lp.id, "slide_id": lp.slide_id, "slide_title": lp.slide_title, "current": lp.current, "parts": lp.parts,
            "status": lp.status, "attempts": lp.attempts, "errors": lp.errors, "model": lp.model,
            "created_at": lp.created_at}


@router.get("/projects/{project_id}/insight-proposals")
def list_proposals(project_id: str, db: Session = Depends(get_db)):
    from app.models import LeadProposal
    get_project(db, project_id)
    rows = db.scalars(select(LeadProposal).where(LeadProposal.project_id == project_id,
                                                 LeadProposal.status.in_(("pending", "failed", "accepted")))
                      .order_by(LeadProposal.created_at.desc()).limit(60))
    return [proposal_out(r) for r in rows]


class ProposalReview(BaseModel):
    action: str  # accept | reject


@router.post("/insight-proposals/{proposal_id}/review")
def review_proposal(proposal_id: str, body: ProposalReview, db: Session = Depends(get_db), who: str = Depends(actor)):
    from app.models import LeadProposal
    from app.services.insights import accept_proposal

    lp = db.get(LeadProposal, proposal_id)
    if lp is None:
        raise not_found("리드 후보")
    if lp.status != "pending":
        raise ApiError(409, "INVALID_STATE", "이미 처리된 후보입니다")
    p = get_project(db, lp.project_id)
    if body.action == "accept":
        accept_proposal(db, lp, p)
    elif body.action == "reject":
        lp.status = "rejected"
    else:
        raise ApiError(422, "INVALID_INPUT", "action은 accept 또는 reject")
    audit(db, p.id, "lead_proposal", lp.id, body.action, after={"slide_id": lp.slide_id}, actor=who)
    db.commit()
    return proposal_out(lp)


@router.delete("/projects/{project_id}/lead-overrides/{slide_id}")
def clear_lead(project_id: str, slide_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Go back to the rule-generated lead for a slide."""
    p = get_project(db, project_id)
    p.lead_overrides = {k: v for k, v in (p.lead_overrides or {}).items() if k != slide_id}
    audit(db, project_id, "slide", slide_id, "lead_reset", actor=who)
    db.commit()
    return {"lead_overrides": list(p.lead_overrides)}


# ------------------------------------------------------------------ P4 case commentary (경쟁사 사례 카드 해설)

class CaseCommentaryIn(BaseModel):
    material_ids: Optional[list[str]] = None


@router.post("/projects/{project_id}/case-commentary", status_code=202)
def start_case_commentary(project_id: str, body: CaseCommentaryIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    from app.config import settings
    from app.services.ledger import run_budget_usd

    p = get_project(db, project_id)
    if not settings.provider_configured("anthropic"):
        raise ApiError(503, "PROVIDER_NOT_CONFIGURED", "Anthropic 키·모델이 설정되지 않았습니다", ".env의 ANTHROPIC_API_KEY·ANTHROPIC_MODEL을 확인하세요")
    if run_budget_usd() <= 0:
        raise ApiError(409, "BUDGET_EXCEEDED", "실행 예산(RUN_BUDGET_USD)이 설정되지 않았습니다")
    running = db.scalar(select(Job).where(Job.project_id == project_id, Job.kind == "case_commentary",
                                          Job.state.in_(("queued", "running"))))
    if running:
        return {"job": job_out(running), "reused": True}
    job, _ = create_job(db, project_id, p.version, "case_commentary", {"material_ids": body.material_ids})
    audit(db, project_id, "case_commentary", job.id, "start", actor=who)
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return {"job": job_out(job), "reused": False}


def commentary_out(c) -> dict:
    return {"id": c.id, "material_id": c.material_id, "detail": c.detail, "implication": c.implication,
            "status": c.status, "attempts": c.attempts, "errors": c.errors, "model": c.model, "created_at": c.created_at}


@router.get("/projects/{project_id}/case-commentary")
def list_case_commentary(project_id: str, db: Session = Depends(get_db)):
    from app.models import CaseCommentary
    get_project(db, project_id)
    rows = db.scalars(select(CaseCommentary).where(CaseCommentary.project_id == project_id,
                                                    CaseCommentary.status.in_(("pending", "failed", "accepted")))
                      .order_by(CaseCommentary.created_at.desc()).limit(60))
    return [commentary_out(r) for r in rows]


class CommentaryReview(BaseModel):
    action: str  # accept | reject


@router.post("/case-commentary/{commentary_id}/review")
def review_case_commentary(commentary_id: str, body: CommentaryReview, db: Session = Depends(get_db), who: str = Depends(actor)):
    from app.models import CaseCommentary
    from app.services.case_commentary import accept_case_commentary

    c = db.get(CaseCommentary, commentary_id)
    if c is None:
        raise not_found("해설 후보")
    if c.status != "pending":
        raise ApiError(409, "INVALID_STATE", "이미 처리된 후보입니다")
    p = get_project(db, c.project_id)
    if body.action == "accept":
        accept_case_commentary(db, c)
    elif body.action == "reject":
        c.status = "rejected"
    else:
        raise ApiError(422, "INVALID_INPUT", "action은 accept 또는 reject")
    audit(db, p.id, "case_commentary", c.id, body.action, after={"material_id": c.material_id}, actor=who)
    db.commit()
    return commentary_out(c)
