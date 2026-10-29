"""Projects and research plans (PRD 4 프로젝트 설정·자동 리서치, P01~P04, R05)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import ROOT, settings
from app.db import get_db
from app.errors import ApiError, not_found, stale_version
from app.models import (
    Claim, Deck, Export, FactRow, ImportBatch, Material, Project, ProviderCall, ResearchItem, ResearchPlan, new_id,
    utcnow,
)
from app.services.audit import audit
from app.services import scope
from app.services.catalog import CHANNELS, DEFAULT_SLIDES, SAMPLE_SLIDES, channel_status, comparison_window
from core.schemas.project import Project as CoreProject
from core.schemas.project import load_project

router = APIRouter()


def actor(x_user: Optional[str] = Header(default=None)) -> str:
    # Internal dev identity until access control lands (DEVELOPMENT_PLAN 단계 4).
    return (x_user or "dev")[:120]


def get_project(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise not_found("프로젝트")
    return p


class ProjectIn(BaseModel):
    name: str
    client: str
    period: dict
    brands: list[dict]
    enabled_slides: Optional[list[str]] = None
    collection_cutoff: Optional[date] = None
    section_windows: Optional[list[dict]] = None
    scope: Optional[list[dict]] = None
    target_hypothesis: Optional[str] = None
    timezone: str = "Asia/Seoul"
    report_profile: Literal["diagnostic"] = "diagnostic"


class ProjectPatch(BaseModel):
    base_version: int
    changes: dict[str, Any]


def _validate(cfg: dict) -> CoreProject:
    try:
        return CoreProject.model_validate(cfg)
    except ValidationError as exc:
        errs = [{"loc": ".".join(str(x) for x in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise ApiError(422, "INVALID_PROJECT", "프로젝트 설정을 확인하세요", "표시된 입력을 수정하세요", errs)
    except ValueError as exc:
        raise ApiError(422, "INVALID_PROJECT", str(exc), "표시된 입력을 수정하세요")


def _with_scope(cfg: dict) -> CoreProject:
    """Validate, then let the scope items set the section windows the deck reads."""
    core = _validate(cfg)
    try:
        scope.validate(core)
    except ValueError as exc:
        raise ApiError(422, "INVALID_PROJECT", str(exc), "조사 범위를 확인하세요")
    cfg["section_windows"] = scope.section_windows(core)
    return _validate(cfg)


def _create_plan(db: Session, project: Project, core: CoreProject, previous: Optional[list[ResearchItem]] = None,
                 version: int = 1) -> ResearchPlan:
    plan = ResearchPlan(id=new_id("PLAN"), project_id=project.id, project_version=project.version, version=version)
    db.add(plan)
    db.flush()
    keep = {(i.brand_id, i.entity, i.scope_id): i for i in (previous or []) if i.scope_id}
    # Items made before the scope existed match on their section (only collector sections had items).
    legacy = {(i.brand_id, i.entity, i.section_id): i for i in (previous or []) if not i.scope_id}
    for spec in scope.generate_items(core):
        old = keep.get((spec["brand_id"], spec["entity"], spec["scope_id"])) or legacy.pop(
            (spec["brand_id"], spec["entity"], spec["section_id"]), None)
        item = ResearchItem(id=new_id("RI"), plan_id=plan.id, project_id=project.id, **spec)
        if old:  # keep the person's decisions when the plan is regenerated
            item.selected, item.review_status, item.omission_reason = old.selected, old.review_status, old.omission_reason
            item.execution_status, item.latest_job_id = old.execution_status, old.latest_job_id
            item.inputs, item.last_result = dict(old.inputs or {}), dict(old.last_result or {})  # e.g. post URLs
            db.query(Material).filter(Material.research_item_id == old.id).update({"research_item_id": item.id})
        db.add(item)
    return plan


def project_out(db: Session, p: Project) -> dict:
    core = CoreProject.model_validate(p.config)
    cmp_start, cmp_end = comparison_window(core)
    # Numbers and sentences of an extra source or an excluded card never reach a slide: nothing to review.
    dup_ids = select(Material.id).where(Material.project_id == p.id,
                                        or_(Material.duplicate_of.is_not(None), Material.review_status == "excluded"))
    counts = {
        "materials": db.scalar(select(func.count()).select_from(Material).where(
            Material.project_id == p.id, Material.duplicate_of.is_(None))),
        "materials_accepted": db.scalar(select(func.count()).select_from(Material).where(
            Material.project_id == p.id, Material.review_status == "accepted", Material.duplicate_of.is_(None))),
        "batches_pending": db.scalar(select(func.count()).select_from(ImportBatch).where(
            ImportBatch.project_id == p.id, ImportBatch.status == "candidate")),
        "materials_candidate": db.scalar(select(func.count()).select_from(Material).where(
            Material.project_id == p.id, Material.review_status == "candidate", Material.duplicate_of.is_(None))),
        "batches": db.scalar(select(func.count()).select_from(ImportBatch).where(
            ImportBatch.project_id == p.id, ImportBatch.status.in_(("candidate", "accepted")))),
        "claims_pending": db.scalar(select(func.count()).select_from(Claim).where(
            Claim.project_id == p.id, Claim.review_status.in_(("pending", "stale")), or_(Claim.material_id.is_(None), Claim.material_id.not_in(dup_ids)))),
        "claims_stale": db.scalar(select(func.count()).select_from(Claim).where(
            Claim.project_id == p.id, Claim.review_status == "stale")),
        "facts_pending": db.scalar(select(func.count()).select_from(FactRow).where(
            FactRow.project_id == p.id, FactRow.origin.in_(("manual", "auto")), FactRow.verification_status == "candidate",
            FactRow.superseded_by.is_(None), or_(FactRow.material_id.is_(None), FactRow.material_id.not_in(dup_ids)))),
        "decks": db.scalar(select(func.count()).select_from(Deck).where(Deck.project_id == p.id)),
        "exports": db.scalar(select(func.count()).select_from(Export).where(Export.project_id == p.id)),
    }
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == p.id).order_by(ResearchPlan.version.desc()))
    if plan:
        items = list(db.scalars(select(ResearchItem).where(ResearchItem.plan_id == plan.id)))
        counts["items"] = len(items)
        counts["items_reviewed"] = sum(1 for i in items if i.review_status != "pending")
        counts["plan_confirmed"] = int(plan.confirmed_at is not None)
    return {
        "id": p.id, "name": p.name, "client": p.client, "version": p.version, "config": p.config,
        "omitted_slots": p.omitted_slots or {}, "updated_at": p.updated_at,
        "comparison_window": {"label": "12M", "start": cmp_start, "end": cmp_end},
        "scope": scope.resolve(core),
        "counts": counts,
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.scalars(select(Project).order_by(Project.updated_at.desc()))
    # What each factbook has cost so far (AI, search, posts) — for the owner on the list, not in the flow.
    spent = dict(db.execute(select(ProviderCall.project_id, func.coalesce(func.sum(ProviderCall.cost_usd), 0.0))
                            .group_by(ProviderCall.project_id)).all())
    return [{"id": p.id, "name": p.name, "client": p.client, "version": p.version, "updated_at": p.updated_at,
             "brands": [b["name"] for b in p.config.get("brands", [])],
             "total_cost_usd": round(float(spent.get(p.id, 0.0)), 4)} for p in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    cfg = body.model_dump(mode="json")
    cfg["enabled_slides"] = cfg.get("enabled_slides") or DEFAULT_SLIDES
    cfg["template_version"] = "1.0"
    cfg["budget_policy"] = {"mode": "offline", "external_calls_enabled": False}
    cfg["section_windows"] = cfg.get("section_windows") or []
    cfg["scope"] = cfg.get("scope") or []
    core = _with_scope(cfg)
    p = Project(id=new_id("PRJ"), name=core.name, client=core.client, config=json.loads(core.model_dump_json()),
                owner=who, omitted_slots={}, lead_overrides={})
    db.add(p)
    db.flush()
    _create_plan(db, p, core)
    audit(db, p.id, "project", p.id, "create", after=p.config, actor=who)
    db.commit()
    return project_out(db, p)


@router.post("/projects/sample", status_code=201)
def create_sample_project(db: Session = Depends(get_db), who: str = Depends(actor)):
    """Demo project from the synthetic quantitative fixture (clearly labelled as synthetic)."""
    raw = json.loads((ROOT / "tests/fixtures/quantitative_samples/project.json").read_text(encoding="utf-8"))
    core = load_project(raw)
    cfg = json.loads(core.model_dump_json())
    cfg["enabled_slides"] = SAMPLE_SLIDES
    cfg["section_windows"] = cfg["section_windows"] + [
        {"section_id": "campaign", "label": "9M", "start": "2026-01-01", "end": "2026-09-30", "source": "user"}]
    cfg["name"] = "샘플 · 브랜드A 진단 (합성 데이터)"
    core = _validate(cfg)
    p = Project(id=new_id("PRJ"), name=core.name, client=core.client, config=json.loads(core.model_dump_json()),
                owner=who, omitted_slots={}, lead_overrides={})
    db.add(p)
    db.flush()
    _create_plan(db, p, core)
    audit(db, p.id, "project", p.id, "create_sample", after=p.config, actor=who)
    db.commit()
    return project_out(db, p)


@router.get("/projects/{project_id}")
def read_project(project_id: str, db: Session = Depends(get_db)):
    return project_out(db, get_project(db, project_id))


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, db: Session = Depends(get_db), who: str = Depends(actor)):
    p = get_project(db, project_id)
    if body.base_version != p.version:
        raise stale_version(p.version, project_out(db, p))
    allowed = {"name", "client", "period", "brands", "enabled_slides", "collection_cutoff", "section_windows",
               "scope", "target_hypothesis"}
    bad = set(body.changes) - allowed
    if bad:
        raise ApiError(422, "INVALID_PROJECT", f"수정할 수 없는 필드: {', '.join(sorted(bad))}")
    cfg = {**p.config, **body.changes}
    core = _with_scope(cfg) if {"scope", "period", "enabled_slides"} & set(body.changes) else _validate(cfg)
    before = p.config
    p.config = json.loads(core.model_dump_json())
    p.name, p.client = core.name, core.client
    p.version += 1
    if {"brands", "enabled_slides", "section_windows", "scope", "period"} & set(body.changes):
        plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == p.id).order_by(ResearchPlan.version.desc()))
        old_items = list(db.scalars(select(ResearchItem).where(ResearchItem.plan_id == plan.id))) if plan else []
        _create_plan(db, p, core, old_items, (plan.version + 1) if plan else 1)
    audit(db, p.id, "project", p.id, "update", before=before, after=p.config, actor=who)
    db.commit()
    return project_out(db, p)


# ------------------------------------------------------------------ research plan

def latest_plan(db: Session, project_id: str) -> ResearchPlan:
    plan = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project_id).order_by(ResearchPlan.version.desc()))
    if plan is None:
        raise not_found("조사 계획")
    return plan


def item_out(db: Session, i: ResearchItem) -> dict:
    linked = list(db.scalars(select(Material).where(Material.research_item_id == i.id)))
    mats = [m for m in linked if not m.duplicate_of]
    accepted = [m for m in mats if m.review_status == "accepted"]
    return {
        "id": i.id, "brand_id": i.brand_id, "entity": i.entity, "role": i.role, "section_id": i.section_id,
        "scope_id": i.scope_id,
        "question": i.question, "period_start": i.period_start, "period_end": i.period_end, "channels": [
            {"id": c, **CHANNELS[c], "status": channel_status(CHANNELS[c]["provider"],
                                                             bool(CHANNELS[c]["provider"]) and settings.provider_configured(CHANNELS[c]["provider"]))}
            for c in i.channels],
        "required": i.required, "selected": i.selected, "execution_status": i.execution_status,
        "review_status": i.review_status, "omission_reason": i.omission_reason, "latest_job_id": i.latest_job_id,
        "coverage": {"materials": len(mats), "accepted": len(accepted), "duplicates": len(linked) - len(mats)}, "order": i.order,
        "inputs": i.inputs or {}, "last_result": i.last_result or {},
    }


@router.get("/projects/{project_id}/research-plan")
def read_plan(project_id: str, db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    plan = latest_plan(db, project_id)
    items = db.scalars(select(ResearchItem).where(ResearchItem.plan_id == plan.id).order_by(ResearchItem.order))
    core = CoreProject.model_validate(p.config)
    # One entry per scope item, in 3C order, with the direction the planner okays before anything runs.
    directions = [{**r, "direction": scope.direction(scope.BY_ID[r["item_id"]], r, core)} for r in scope.resolve(core)]
    return {"id": plan.id, "version": plan.version, "project_version": plan.project_version,
            "confirmed_at": plan.confirmed_at, "scope": directions, "items": [item_out(db, i) for i in items]}


class PlanItemPatch(BaseModel):
    id: str
    selected: Optional[bool] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class PlanPut(BaseModel):
    base_version: int
    items: list[PlanItemPatch] = Field(default_factory=list)
    confirm: bool = True


@router.put("/projects/{project_id}/research-plan")
def put_plan(project_id: str, body: PlanPut, db: Session = Depends(get_db), who: str = Depends(actor)):
    get_project(db, project_id)
    plan = latest_plan(db, project_id)
    if body.base_version != plan.version:
        raise stale_version(plan.version)
    items = {i.id: i for i in db.scalars(select(ResearchItem).where(ResearchItem.plan_id == plan.id))}
    for patch in body.items:
        item = items.get(patch.id)
        if item is None:
            raise not_found("조사 항목")
        if patch.selected is not None:
            item.selected = patch.selected
        if patch.period_start or patch.period_end:
            start, end = patch.period_start or item.period_start, patch.period_end or item.period_end
            if start > end:
                raise ApiError(422, "INVALID_PERIOD", "시작일이 종료일보다 늦습니다")
            item.period_start, item.period_end = start, end
    plan.version += 1
    if body.confirm:
        plan.confirmed_at = utcnow()
    audit(db, project_id, "research_plan", plan.id, "update", after=[p.model_dump(mode="json") for p in body.items], actor=who)
    db.commit()
    return read_plan(project_id, db)


class RunIn(BaseModel):
    item_ids: list[str]
    force: bool = False


@router.post("/projects/{project_id}/research-runs", status_code=202)
def start_run(project_id: str, body: RunIn, db: Session = Depends(get_db), who: str = Depends(actor),
              idempotency_key: Optional[str] = Header(default=None)):
    """Run automatic research for the chosen items (server job; survives a closed browser)."""
    from app.jobs import create_job, dispatch
    from app.models import Job

    p = get_project(db, project_id)
    items = [db.get(ResearchItem, i) for i in body.item_ids]
    if not items or any(i is None or i.project_id != project_id for i in items):
        raise not_found("조사 항목")
    providers = sorted({CHANNELS[c]["provider"] for i in items for c in i.channels if CHANNELS.get(c, {}).get("provider")})
    missing = [x for x in providers if not settings.provider_configured(x)]
    if missing:
        raise ApiError(503, "PROVIDER_NOT_CONFIGURED", f"자동 수집 키가 설정되지 않았습니다({', '.join(missing)})",
                       "자료 수집 탭에서 직접 추가하거나 CSV를 업로드하세요", {"providers": missing})
    # Runs may overlap in time; only the same item cannot be researched by two runs at once.
    busy: dict[str, str] = {}
    for running in db.scalars(select(Job).where(Job.project_id == project_id, Job.kind == "research_run",
                                                Job.state.in_(("queued", "running")))):
        for iid in running.params.get("item_ids", []):
            busy[iid] = running.id
    clash = [i for i in items if i.id in busy]
    if clash:
        raise ApiError(409, "JOB_RUNNING", f"이미 조사 중인 항목이 있습니다: {', '.join(i.entity for i in clash)}",
                       "그 항목의 조사가 끝난 뒤 다시 실행하거나, 다른 항목만 골라 실행하세요",
                       {"job_id": busy[clash[0].id], "item_ids": [i.id for i in clash]})
    job, created = create_job(db, project_id, p.version, "research_run", {"item_ids": body.item_ids, "force": body.force},
                              idempotency_key)
    if created:
        for i in items:
            if i.execution_status != "succeeded" or body.force:
                i.execution_status, i.latest_job_id = "queued", job.id
        audit(db, project_id, "research_run", job.id, "start", after={"items": body.item_ids, "force": body.force}, actor=who)
        db.commit()
        dispatch(job.id)
        db.refresh(job)
    return {"job": {"id": job.id, "state": job.state, "progress": job.progress}}


class ItemInputs(BaseModel):
    post_urls: list[str] = Field(default_factory=list)
    hashtags: Optional[list[str]] = None  # Instagram hashtags to discover posts with (Apify); None keeps the saved ones


@router.put("/research-items/{item_id}/inputs")
def set_item_inputs(item_id: str, body: ItemInputs, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Post URLs a person chose for an influencer item (no unbounded account crawling)."""
    from integrations.scrapecreators.client import platform_of

    item = db.get(ResearchItem, item_id)
    if item is None:
        raise not_found("조사 항목")
    urls = [u.strip() for u in body.post_urls if u.strip()]
    bad = [u for u in urls if platform_of(u) is None]
    if bad:
        raise ApiError(422, "UNSUPPORTED_URL", "Instagram·YouTube 게시물 URL만 넣을 수 있습니다", "다른 채널은 자료 카드로 직접 추가하세요",
                       {"urls": bad[:5]})
    if len(urls) > 40:
        raise ApiError(422, "LIMIT", "한 항목에 최대 40개 URL까지 넣을 수 있습니다")
    item.inputs = {**(item.inputs or {}), "post_urls": list(dict.fromkeys(urls))}
    if body.hashtags is not None:
        tags = [t.strip().lstrip("#") for t in body.hashtags if t.strip().lstrip("#")]
        if len(tags) > 5:
            raise ApiError(422, "LIMIT", "해시태그는 최대 5개까지 넣을 수 있습니다")
        item.inputs["hashtags"] = list(dict.fromkeys(tags))
    if item.execution_status == "succeeded":
        item.execution_status = "not_started"  # new inputs need a new run
    audit(db, item.project_id, "research_item", item.id, "inputs", after={"post_urls": len(urls), "hashtags": (item.inputs or {}).get("hashtags", [])}, actor=who)
    db.commit()
    return item_out(db, item)


@router.get("/projects/{project_id}/usage")
def usage(project_id: str, db: Session = Depends(get_db)):
    from app.services.ledger import usage_summary
    get_project(db, project_id)
    return usage_summary(db, project_id)


class ItemReview(BaseModel):
    review_status: Literal["pending", "accepted", "excluded"]
    omission_reason: Optional[str] = None


@router.patch("/research-items/{item_id}/review")
def review_item(item_id: str, body: ItemReview, db: Session = Depends(get_db), who: str = Depends(actor)):
    item = db.get(ResearchItem, item_id)
    if item is None:
        raise not_found("조사 항목")
    if body.review_status == "excluded" and not (body.omission_reason or "").strip():
        raise ApiError(422, "REASON_REQUIRED", "제외할 때는 사유를 입력하세요")
    before = {"review_status": item.review_status, "omission_reason": item.omission_reason}
    item.review_status = body.review_status
    item.omission_reason = body.omission_reason if body.review_status == "excluded" else None
    audit(db, item.project_id, "research_item", item.id, "review", before=before,
          after=body.model_dump(), reason=body.omission_reason, actor=who)
    db.commit()
    return item_out(db, item)


@router.post("/projects/{project_id}/research-plan/accept-all")
def accept_all_items(project_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    """확인 완료 for every item still waiting in the latest plan, in one step (excluded items stay excluded)."""
    get_project(db, project_id)
    plan = latest_plan(db, project_id)
    items = list(db.scalars(select(ResearchItem).where(ResearchItem.plan_id == plan.id, ResearchItem.selected.is_(True),
                                                       ResearchItem.review_status.in_(("pending", "stale")))))
    for i in items:
        i.review_status = "accepted"
    audit(db, project_id, "research_plan", plan.id, "accept_all", after={"items": [i.id for i in items]}, actor=who)
    db.commit()
    return {"accepted": len(items)}


@router.get("/projects/{project_id}/history")
def history(project_id: str, db: Session = Depends(get_db)):
    from app.models import AuditLog
    rows = db.scalars(select(AuditLog).where(AuditLog.project_id == project_id).order_by(AuditLog.id.desc()).limit(200))
    return [{"entity": r.entity, "entity_id": r.entity_id, "action": r.action, "reason": r.reason, "actor": r.actor,
             "at": r.at} for r in rows]
