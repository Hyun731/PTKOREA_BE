"""CSV imports, material cards, images, claims and manual facts (PRD 7, 8; M01~M04, F01~F03, W04)."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import ROOT, settings
from app.db import get_db
from app.errors import ApiError, not_found, stale_version
from app.models import (
    Asset, Claim, FactRow, ImportBatch, Material, PostRow, ResearchItem, Source, new_id, utcnow,
)
from app.routers.projects import actor, get_project
from app.services.assets import inspect_upload, normalized_derivative, validate_crop
from app.services.audit import audit
from app.services.inputs import core_project
from app.storage import get_storage
from core.composition.formatters import UNIT_FORMATTER, fmt_date_dot, format_value
from core.ingestion.csv_import import import_facts_csv, import_posts_csv
from core.ingestion.manual import make_manual_fact
from core.schemas.facts import MANUAL_METRICS, Fact
from core.schemas.materials import TARGET_SEGMENTS

router = APIRouter()
DIGIT = re.compile(r"\d")
# A written-out date (2026.03.15, 2026-03-15, 2026년 3월 15일, 3월 15일 ...) needs no Fact behind it —
# only a claimed number/figure does. Strip date-shaped digits before flagging unbound numbers.
DATE_LIKE = re.compile(r"\d{4}[.\-/]\d{1,2}(?:[.\-/]\d{1,2})?|\d{4}년\s?\d{1,2}월(?:\s?\d{1,2}일)?|\d{1,2}월\s?\d{1,2}일")


def _unbound_digit(text: str) -> bool:
    return bool(DIGIT.search(DATE_LIKE.sub("", text)))


# ------------------------------------------------------------------ CSV imports

def batch_out(b: ImportBatch) -> dict:
    return {"id": b.id, "kind": b.kind, "filename": b.filename, "status": b.status, "total_rows": b.total_rows,
            "valid_rows": b.valid_rows, "errors": b.errors, "duplicates": b.duplicates, "synthetic": b.synthetic,
            "reviewed_by": b.reviewed_by, "reviewed_at": b.reviewed_at, "created_at": b.created_at}


def _store_batch(db: Session, project, kind: str, filename: str, text: str, who: str,
                 source_name: str = "posts.csv") -> ImportBatch:
    core = core_project(project)
    batch_id = new_id("BAT")
    result = (import_facts_csv(text, core, batch_id, filename) if kind == "facts"
              else import_posts_csv(text, core, batch_id, filename, source_name))
    if any(e.code == "MISSING_COLUMN" for e in result.errors):
        raise ApiError(422, "INVALID_ROW", "필수 열이 없습니다", "템플릿 열 이름을 확인하세요",
                       [e.model_dump() for e in result.errors])
    key = get_storage().put_bytes(f"imports/{project.id}/{batch_id}/{filename}", text.encode("utf-8"))
    synthetic = any(f.source == "synthetic_fixture" for f in result.facts)
    valid = len(result.facts) if kind == "facts" else len(result.posts)
    batch = ImportBatch(id=batch_id, project_id=project.id, kind=kind, filename=filename, total_rows=result.total_rows,
                        valid_rows=valid, errors=[e.model_dump() for e in result.errors],
                        duplicates=[d.model_dump() for d in result.duplicates], file_key=key, synthetic=synthetic)
    db.add(batch)
    for f in result.facts:
        db.add(FactRow(project_id=project.id, fact_id=f.id, origin="csv" if kind == "facts" else "posts",
                       batch_id=batch_id, data=json.loads(f.model_dump_json()), verification_status="candidate"))
    for p in result.posts:
        db.add(PostRow(project_id=project.id, batch_id=batch_id, post_id=p.post_id, data=json.loads(p.model_dump_json())))
    audit(db, project.id, "import_batch", batch_id, "upload", after={"file": filename, "valid": valid,
                                                                     "errors": len(result.errors)}, actor=who)
    return batch


@router.post("/projects/{project_id}/imports", status_code=201)
async def upload_import(project_id: str, kind: Literal["facts", "posts"] = Form(...), file: UploadFile = File(...),
                        db: Session = Depends(get_db), who: str = Depends(actor)):
    p = get_project(db, project_id)
    data = await file.read()
    if len(data) > settings.max_csv_bytes:
        raise ApiError(413, "FILE_TOO_LARGE", "CSV는 5MB 이하만 업로드할 수 있습니다")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ApiError(422, "INVALID_ROW", "UTF-8 CSV만 지원합니다", "UTF-8(BOM 허용)로 저장해 다시 업로드")
    batch = _store_batch(db, p, kind, (file.filename or f"{kind}.csv")[-120:], text, who)
    db.commit()
    return batch_out(batch)


FIXTURE_ENTITIES = ["브랜드A", "경쟁X", "경쟁Y"]


def _facts_fixture_for(p) -> str:
    """The fixture hard-codes a generic brand/competitor set. Projects created via
    /projects/sample (or any manual project) use their own names, so the fixture's
    entity names are remapped onto the project's first brand's entity_set — else
    every row fails with UNKNOWN_ENTITY. Falls back to the raw fixture if the brand
    doesn't have at least two competitors to map onto."""
    base = ROOT / "tests/fixtures/quantitative_samples"
    text = (base / "facts.csv").read_text(encoding="utf-8")
    brands = core_project(p).brands
    entities = brands[0].entity_set if brands else []
    if len(entities) < len(FIXTURE_ENTITIES):
        return text
    for placeholder, real in zip(FIXTURE_ENTITIES, entities):
        text = text.replace(placeholder, real)
    return text


@router.post("/projects/{project_id}/imports/sample", status_code=201)
def import_sample(project_id: str, posts: Literal["posts.csv", "posts_13.csv"] = "posts.csv",
                  db: Session = Depends(get_db), who: str = Depends(actor)):
    """Synthetic quantitative fixture for demos; batches still need explicit acceptance."""
    p = get_project(db, project_id)
    base = ROOT / "tests/fixtures/quantitative_samples"
    out = [_store_batch(db, p, "facts", "facts.csv", _facts_fixture_for(p), who),
           _store_batch(db, p, "posts", posts, (base / posts).read_text(encoding="utf-8"), who)]
    for b in out:
        b.synthetic = True  # the whole fixture is synthetic, posts included
    db.commit()
    return [batch_out(b) for b in out]


@router.get("/projects/{project_id}/imports")
def list_imports(project_id: str, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return [batch_out(b) for b in db.scalars(select(ImportBatch).where(ImportBatch.project_id == project_id)
                                              .order_by(ImportBatch.created_at.desc()))]


class BatchReview(BaseModel):
    action: Literal["accept", "reject"]
    reason: Optional[str] = None


def _batch_brands(db: Session, b: ImportBatch) -> set[str]:
    rows = PostRow if b.kind == "posts" else FactRow
    return {d.get("brand_id") for d in db.scalars(select(rows.data).where(rows.batch_id == b.id))} - {None}


@router.post("/imports/{batch_id}/review")
def review_batch(batch_id: str, body: BatchReview, db: Session = Depends(get_db), who: str = Depends(actor)):
    b = db.get(ImportBatch, batch_id)
    if b is None:
        raise not_found("CSV 배치")
    if b.status not in ("candidate", "accepted", "rejected"):
        raise ApiError(409, "INVALID_STATE", "교체된 배치는 검토할 수 없습니다")
    before = b.status
    b.status = "accepted" if body.action == "accept" else "rejected"
    b.reviewed_by, b.reviewed_at = who, utcnow()
    if body.action == "accept":
        # Same-kind earlier accepted batches are replaced only within imports (manual data untouched),
        # and only when they cover a brand this batch also covers: research writes one posts CSV per brand.
        mine = _batch_brands(db, b)
        for other in db.scalars(select(ImportBatch).where(ImportBatch.project_id == b.project_id, ImportBatch.kind == b.kind,
                                                          ImportBatch.status == "accepted", ImportBatch.id != b.id)):
            theirs = _batch_brands(db, other)
            if not mine or not theirs or mine & theirs:
                other.status = "replaced"
    audit(db, b.project_id, "import_batch", b.id, body.action, before=before, after=b.status, reason=body.reason, actor=who)
    db.commit()
    return batch_out(b)


@router.get("/imports/{batch_id}/errors.csv")
def batch_errors(batch_id: str, db: Session = Depends(get_db)):
    b = db.get(ImportBatch, batch_id)
    if b is None:
        raise not_found("CSV 배치")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["file", "row_no", "column", "code", "message"])
    for e in b.errors:
        w.writerow([e["file"], e["row_no"], e.get("column") or "", e["code"], e["message"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="errors-{b.id}.csv"'})


# ------------------------------------------------------------------ materials

def _check_target_segment(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in TARGET_SEGMENTS:
        raise ApiError(422, "INVALID_TARGET_SEGMENT", f"지원하는 값: {', '.join(TARGET_SEGMENTS)}")
    return v


def _check_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ApiError(422, "INVALID_URL", "http/https URL만 등록할 수 있습니다")
    return url


class MaterialIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[date] = None
    brand_id: Optional[str] = None
    entity: Optional[str] = None
    section_id: Literal["campaign", "market", "influencer", "search"] = "campaign"
    label: Optional[str] = None
    comment: str = ""
    excerpt: str = ""
    activity_date: Optional[date] = None
    activity_date_end: Optional[date] = None
    research_item_id: Optional[str] = None
    target_segment: Optional[str] = None  # 1-6 매트릭스 행; TARGET_SEGMENTS 중 하나


class MaterialPatch(BaseModel):
    base_version: int
    title: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[date] = None
    brand_id: Optional[str] = None
    entity: Optional[str] = None
    section_id: Optional[Literal["campaign", "market", "influencer", "search"]] = None
    label: Optional[str] = None
    comment: Optional[str] = None
    excerpt: Optional[str] = None
    activity_date: Optional[date] = None
    activity_date_end: Optional[date] = None
    featured: Optional[bool] = None
    order: Optional[int] = None
    target_segment: Optional[str] = None
    ai_detail: Optional[str] = None  # P4 사례 카드 해설 — 수동 수정·초기화(null)용
    ai_implication: Optional[str] = None


def material_out(db: Session, m: Material, detail: bool = False) -> dict:
    src = db.get(Source, m.source_id)
    assets = list(db.scalars(select(Asset).where(Asset.material_id == m.id).order_by(Asset.created_at)))
    claims = list(db.scalars(select(Claim).where(Claim.material_id == m.id).order_by(Claim.created_at)))
    facts = list(db.scalars(select(FactRow).where(FactRow.material_id == m.id).order_by(FactRow.created_at)))
    out = {
        "id": m.id, "version": m.version, "title": m.title, "label": m.label, "brand_id": m.brand_id, "entity": m.entity,
        "section_id": m.section_id, "comment": m.comment, "excerpt": m.excerpt, "input_path": m.input_path,
        "review_status": m.review_status, "review_reason": m.review_reason, "reviewed_by": m.reviewed_by,
        "reviewed_at": m.reviewed_at, "activity_date": m.activity_date, "activity_date_end": m.activity_date_end,
        "research_item_id": m.research_item_id, "selected_asset_id": m.selected_asset_id, "order": m.order,
        "featured": m.featured,
        "source": {"id": src.id, "title": src.title, "url": src.original_url, "publisher": src.publisher,
                   "published_at": src.published_at, "fetched_at": src.fetched_at, "access_status": src.access_status,
                   "source_type": src.source_type},
        "assets": [asset_out(a) for a in assets],
        "claims": [claim_out(c) for c in claims],
        "facts": [fact_out(f) for f in facts if f.superseded_by is None],
        "readiness": _readiness(m, assets, claims),
        "duplicate_of": m.duplicate_of, "duplicate_reason": m.duplicate_reason, "event_name": m.event_name,
        "summary": m.summary,
        "duplicates": [{"id": d.id, "title": d.title, "reason": d.duplicate_reason, "url": s.original_url,
                        "publisher": s.publisher, "published_at": s.published_at, "review_status": d.review_status}
                       for d, s in db.execute(select(Material, Source).join(Source, Source.id == Material.source_id)
                                              .where(Material.duplicate_of == m.id).order_by(Material.created_at))],
        "target_segment": m.target_segment, "ai_detail": m.ai_detail, "ai_implication": m.ai_implication,
        "created_at": m.created_at, "updated_at": m.updated_at,
    }
    if detail:
        out["fact_history"] = [fact_out(f) for f in facts if f.superseded_by]
    return out


def _readiness(m: Material, assets: list[Asset], claims: list[Claim]) -> list[str]:
    """What still blocks this card from a case slide (shown on the card)."""
    missing = []
    if m.duplicate_of:
        return ["같은 사례의 추가 출처 (장표에는 대표 자료만 쓰임)"]
    if m.review_status != "accepted":
        missing.append("자료 채택")
    if m.section_id in ("campaign", "influencer"):
        sel = next((a for a in assets if a.id == m.selected_asset_id), None)
        if not sel or sel.review_status != "accepted":
            missing.append("이미지 선택·채택")
    if m.section_id in ("campaign", "market") and not any(c.review_status == "accepted" for c in claims):
        missing.append("근거 문장 채택")
    if any(c.review_status == "stale" for c in claims):
        missing.append("근거 변경 재검토")
    return missing


def get_material(db: Session, material_id: str) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise not_found("자료")
    return m


@router.post("/projects/{project_id}/materials", status_code=201)
def create_material(project_id: str, body: MaterialIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    p = get_project(db, project_id)
    core = core_project(p)
    if body.brand_id and body.brand_id not in {b.id for b in core.brands}:
        raise ApiError(422, "UNKNOWN_BRAND", "프로젝트에 없는 브랜드입니다")
    if body.research_item_id:
        item = db.get(ResearchItem, body.research_item_id)
        if item is None or item.project_id != project_id:
            raise not_found("조사 항목")
    src = Source(id=new_id("SRC"), project_id=project_id, title=body.title, original_url=_check_url(body.url),
                 publisher=body.publisher, published_at=body.published_at,
                 source_type="web" if body.url else "upload", access_status="unknown")
    db.add(src)
    db.flush()  # the source row must exist before the card references it
    # 0 = no explicit position: cases follow brand order then date, whether typed in or researched.
    order = 0
    m = Material(id=new_id("EV"), project_id=project_id, source_id=src.id, research_item_id=body.research_item_id,
                 brand_id=body.brand_id, entity=body.entity, section_id=body.section_id, title=body.title,
                 label=body.label, comment=body.comment, excerpt=body.excerpt, activity_date=body.activity_date,
                 activity_date_end=body.activity_date_end, target_segment=_check_target_segment(body.target_segment),
                 input_path="manual", order=order)
    db.add(m)
    audit(db, project_id, "material", m.id, "create", after=body.model_dump(mode="json"), actor=who)
    db.commit()
    return material_out(db, m)


@router.get("/projects/{project_id}/materials")
def list_materials(project_id: str, brand_id: Optional[str] = None, section_id: Optional[str] = None,
                   status: Optional[str] = None, db: Session = Depends(get_db)):
    get_project(db, project_id)
    q = select(Material).where(Material.project_id == project_id)
    if brand_id:
        q = q.where(Material.brand_id == brand_id)
    if section_id:
        q = q.where(Material.section_id == section_id)
    if status:
        q = q.where(Material.review_status == status)
    return [material_out(db, m) for m in db.scalars(q.order_by(Material.order, Material.created_at))]


@router.get("/materials/{material_id}")
def read_material(material_id: str, db: Session = Depends(get_db)):
    return material_out(db, get_material(db, material_id), detail=True)


@router.patch("/materials/{material_id}")
def patch_material(material_id: str, body: MaterialPatch, db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    if body.base_version != m.version:
        raise stale_version(m.version, material_out(db, m))
    changes = body.model_dump(exclude_unset=True, exclude={"base_version"})
    src = db.get(Source, m.source_id)
    before = material_out(db, m)
    source_changed = False
    for k, v in changes.items():
        if k == "url":
            v = _check_url(v)
            source_changed = source_changed or v != src.original_url
            src.original_url = v
        elif k == "publisher":
            src.publisher = v
        elif k == "published_at":
            source_changed = source_changed or v != src.published_at
            src.published_at = v
        elif k == "target_segment":
            setattr(m, k, _check_target_segment(v))
        else:
            setattr(m, k, v)
            if k == "title":
                src.title = v
    if source_changed:
        # Evidence changed: claims built on it need a fresh review (PRD 4, A16).
        for c in db.scalars(select(Claim).where(Claim.material_id == m.id, Claim.review_status == "accepted")):
            c.review_status, c.stale_reason = "stale", "출처 정보가 변경되었습니다"
    m.version += 1
    audit(db, m.project_id, "material", m.id, "update", before=before, after=changes, actor=who)
    db.commit()
    return material_out(db, m)


class ReviewIn(BaseModel):
    status: Literal["candidate", "accepted", "excluded"]
    reason: Optional[str] = None


@router.patch("/materials/{material_id}/review")
def review_material(material_id: str, body: ReviewIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    if body.status == "excluded" and not (body.reason or "").strip():
        body.reason = "사용자가 제외"  # one click; the card moves to "제외된 자료" and can come back
    if body.status == "accepted" and m.duplicate_of:
        raise ApiError(409, "IS_DUPLICATE", "같은 사례로 묶인 추가 출처입니다",
                       "대표 자료를 채택하거나, 별개 사례라면 먼저 분리하세요")
    before = m.review_status
    m.review_status, m.review_reason, m.reviewed_by, m.reviewed_at = body.status, body.reason, who, utcnow()
    m.version += 1
    audit(db, m.project_id, "material", m.id, "review", before=before, after=body.status, reason=body.reason, actor=who)
    db.commit()
    return material_out(db, m)


class DuplicateIn(BaseModel):
    of: Optional[str] = None  # primary material id; null splits the card off as its own activity
    make_primary: bool = False  # swap: this card becomes the primary of its group


@router.post("/materials/{material_id}/duplicate")
def set_duplicate(material_id: str, body: DuplicateIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Group a card under another one about the same activity, split it off, or make it the primary."""
    from app.services import dedupe
    m = get_material(db, material_id)
    before = {"duplicate_of": m.duplicate_of}
    if body.make_primary:
        if not m.duplicate_of:
            raise ApiError(409, "NOT_DUPLICATE", "이미 대표 자료입니다")
        old = db.get(Material, m.duplicate_of)
        m.duplicate_of, m.duplicate_reason = None, None
        m.version += 1
        dedupe.merge(db, old, m, "대표 자료를 바꿈")
        if old.review_status == "accepted":  # the slide follows the primary: carry the decision over
            old.review_status, m.review_status = "candidate", "accepted"
            m.reviewed_by, m.reviewed_at = who, utcnow()
    elif body.of:
        primary = get_material(db, body.of)
        if primary.project_id != m.project_id or primary.id == m.id or primary.duplicate_of == m.id:
            raise ApiError(422, "INVALID_PRIMARY", "같은 프로젝트의 다른 자료를 대표로 고르세요")
        dedupe.merge(db, m, primary, "사람이 같은 사례로 묶음")
        if m.review_status == "accepted":
            m.review_status = "candidate"
    else:
        if not m.duplicate_of:
            raise ApiError(409, "NOT_DUPLICATE", "묶여 있지 않은 자료입니다")
        dedupe.split(m)
    audit(db, m.project_id, "material", m.id, "duplicate", before=before, after=body.model_dump(), actor=who)
    db.commit()
    return material_out(db, m)


@router.post("/projects/{project_id}/materials/dedupe")
def dedupe_materials(project_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Find cards about the same activity among what is already collected (no paid calls)."""
    from app.services import dedupe
    p = get_project(db, project_id)
    merged = dedupe.scan(db, p)
    if merged:
        audit(db, project_id, "material", project_id, "dedupe", after=merged, actor=who)
    db.commit()
    return {"merged": merged}


@router.post("/projects/{project_id}/materials/period-check")
def period_check(project_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Re-apply the research period rule to auto-collected candidates (no paid calls)."""
    from app.services import period
    p = get_project(db, project_id)
    out = period.recheck(db, p)
    if out["excluded"]:
        audit(db, project_id, "material", project_id, "period_check", after=out["excluded"], actor=who)
    db.commit()
    return out


# ------------------------------------------------------------------ assets

def asset_out(a: Asset) -> dict:
    return {"id": a.id, "version": a.version, "material_id": a.material_id, "width": a.width, "height": a.height,
            "mime_type": a.mime_type, "sha256": a.sha256, "crop": a.crop, "crop_history": a.crop_history,
            "title": a.title, "description": a.description, "usage_basis": a.usage_basis,
            "review_status": a.review_status, "created_at": a.created_at}


@router.post("/materials/{material_id}/assets", status_code=201)
async def upload_asset(material_id: str, file: UploadFile = File(...), title: str = Form(""), description: str = Form(""),
                       usage_basis: Literal["user_provided", "source_reference", "licensed"] = Form("user_provided"),
                       db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    count = db.scalar(select(func.count()).select_from(Asset).where(Asset.project_id == m.project_id))
    if count >= settings.max_images_per_project:
        raise ApiError(409, "QUOTA_EXCEEDED", "프로젝트 이미지 한도(100장)를 넘었습니다", "사용하지 않는 이미지를 정리하세요")
    data = await file.read()
    mime, width, height, sha = inspect_upload(data)
    dup = db.scalar(select(Asset).where(Asset.material_id == m.id, Asset.sha256 == sha))
    if dup:
        return asset_out(dup)
    storage = get_storage()
    asset_id = new_id("AS")
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
    original_key = storage.put_bytes(f"assets/{m.project_id}/{asset_id}/original.{ext}", data)
    derived, dext = normalized_derivative(data)
    derived_key = storage.put_bytes(f"assets/{m.project_id}/{asset_id}/derived.{dext}", derived)
    a = Asset(id=asset_id, project_id=m.project_id, material_id=m.id, source_id=m.source_id, original_key=original_key,
              derived_key=derived_key, sha256=sha, mime_type=mime, width=width, height=height,
              title=title or m.title, description=description, usage_basis=usage_basis)
    db.add(a)
    if not m.selected_asset_id:
        m.selected_asset_id = a.id
        m.version += 1
    audit(db, m.project_id, "asset", a.id, "upload", after={"sha256": sha, "w": width, "h": height}, actor=who)
    db.commit()
    return asset_out(a)


def get_asset(db: Session, asset_id: str) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None:
        raise not_found("이미지")
    return a


class CropIn(BaseModel):
    base_version: int
    crop: dict


@router.post("/materials/{material_id}/fetch-source")
def fetch_source(material_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Read the card's original URL (no AI, no paid call): image candidates, publisher, publish date and an
    excerpt to write claims from — what automatic research does for its own cards, for a card made by hand."""
    from app.services import research
    from integrations.base import ProviderError
    m = get_material(db, material_id)
    src = db.get(Source, m.source_id)
    if not src or not src.original_url:
        raise ApiError(422, "NO_URL", "원문 URL이 없는 자료입니다", "출처 정보에 원문 URL을 먼저 입력하세요")
    p = research._providers()
    try:
        page = p["fetch_page"](src.original_url)
    except ProviderError as exc:
        src.access_status = "unavailable"
        db.commit()
        raise ApiError(502, exc.code, f"원문을 가져오지 못했습니다: {exc.message}", "이미지를 직접 올려 주세요")
    images = []
    for url in page.image_urls[:5]:
        try:
            images.append(p["fetch_image"](url))
        except ProviderError:
            continue
        if len(images) == 3:
            break
    known = {a.sha256 for a in db.scalars(select(Asset).where(Asset.material_id == m.id))}
    saved = [a for a in (research._save_image_candidate(db, m, data, m.title) for data in images) if a and a.sha256 not in known]
    if saved and not m.selected_asset_id:
        m.selected_asset_id = saved[0].id
        research._prefer_specific_image(db, m, src, saved)
    src.access_status, src.content_hash = "ok", page.content_hash
    src.text = page.text[:research.SOURCE_TEXT_CHARS] if page.text else src.text
    src.publisher = src.publisher or page.publisher
    src.published_at = src.published_at or research._safe_date(page.published)
    if not m.excerpt and page.text:
        m.excerpt = research._norm(page.text)[:1200]
    m.version += 1
    audit(db, m.project_id, "material", m.id, "fetch_source", after={"images": len(saved)}, actor=who)
    db.commit()
    return material_out(db, m)


@router.patch("/assets/{asset_id}/crop")
def crop_asset(asset_id: str, body: CropIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    a = get_asset(db, asset_id)
    if body.base_version != a.version:
        raise stale_version(a.version, asset_out(a))
    crop = validate_crop(body.crop)
    a.crop_history = [*a.crop_history, {"version": a.version, "crop": a.crop, "at": utcnow().isoformat()}]
    a.crop, a.version = crop, a.version + 1  # original file untouched; new crop version
    audit(db, a.project_id, "asset", a.id, "crop", after=crop, actor=who)
    db.commit()
    return asset_out(a)


class AssetMeta(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    usage_basis: Optional[Literal["user_provided", "source_reference", "licensed"]] = None
    review_status: Optional[Literal["candidate", "accepted", "excluded"]] = None


@router.patch("/assets/{asset_id}")
def patch_asset(asset_id: str, body: AssetMeta, db: Session = Depends(get_db), who: str = Depends(actor)):
    a = get_asset(db, asset_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(a, k, v)
    a.version += 1
    audit(db, a.project_id, "asset", a.id, "update", after=changes, actor=who)
    db.commit()
    return asset_out(a)


class SelectAsset(BaseModel):
    asset_id: Optional[str]


@router.post("/materials/{material_id}/select-asset")
def select_asset(material_id: str, body: SelectAsset, db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    if body.asset_id:
        a = get_asset(db, body.asset_id)
        if a.material_id != m.id:
            raise ApiError(422, "INVALID_ASSET", "이 자료에 속한 이미지만 선택할 수 있습니다")
    m.selected_asset_id = body.asset_id
    m.version += 1
    audit(db, m.project_id, "material", m.id, "select_asset", after=body.asset_id, actor=who)
    db.commit()
    return material_out(db, m)


@router.get("/projects/{project_id}/owned-posts")
def list_owned_posts(project_id: str, db: Session = Depends(get_db)):
    """2-4 브랜드별 상위 게시물 후보 — 자료 카드가 없는 자산이라 /materials로는 안 보임.
    PATCH /assets/{asset_id}로 이미지를 채택해야 2-4 슬라이드에 들어간다."""
    from app.models import OwnedPost
    get_project(db, project_id)
    rows = db.scalars(select(OwnedPost).where(OwnedPost.project_id == project_id).order_by(OwnedPost.likes.desc()))
    out = []
    for r in rows:
        asset = db.get(Asset, r.asset_id) if r.asset_id else None
        out.append({"id": r.id, "brand_id": r.brand_id, "channel": r.channel, "url": r.url, "posted_at": r.posted_at,
                   "likes": r.likes, "comments": r.comments, "asset": asset_out(asset) if asset else None})
    return out


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: str, variant: Literal["original", "derived"] = "derived", db: Session = Depends(get_db)):
    a = get_asset(db, asset_id)
    key = a.original_key if variant == "original" else a.derived_key
    path = get_storage().path(key)
    return FileResponse(path, media_type=a.mime_type if variant == "original" else
                        ("image/png" if key.endswith(".png") else "image/jpeg"),
                        headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ claims

TOKEN = re.compile(r"\{\{(F-[0-9a-f]{20})(?:\|([a-z_]+))?\}\}|\[\[(.+?)\]\]|\{\{d:(\d{4}-\d{2}-\d{2})\}\}")


def parse_claim_text(db: Session, project_id: str, text: str) -> tuple[list[dict], list[str], list[str]]:
    """Text with {{F-…}} fact tokens, [[name]] fixed names and {{d:YYYY-MM-DD}} dates -> typed parts.
    Returns (parts, fact_ids, issues)."""
    parts: list[dict] = []
    fact_ids: list[str] = []
    issues: list[str] = []
    pos = 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            parts.append({"type": "text", "text": text[pos:m.start()]})
        fid, formatter, name, day = m.groups()
        if fid:
            row = db.scalar(select(FactRow).where(FactRow.project_id == project_id, FactRow.fact_id == fid))
            if row is None:
                issues.append(f"없는 Fact {fid}")
                parts.append({"type": "text", "text": m.group(0)})
            else:
                fact = Fact.model_validate(row.data)
                fmt = formatter or UNIT_FORMATTER.get(fact.unit, "int")
                parts.append({"type": "fact", "fact_id": fid, "formatter": fmt,
                              "display": format_value(fmt, fact.value), "bold": True})
                fact_ids.append(fid)
        elif name:
            parts.append({"type": "name", "text": name})
        else:
            parts.append({"type": "date", "text": fmt_date_dot(date.fromisoformat(day))})
        pos = m.end()
    if pos < len(text):
        parts.append({"type": "text", "text": text[pos:]})
    for p in parts:
        if p["type"] == "text" and _unbound_digit(p["text"]):
            issues.append(f"근거 없는 숫자: '{p['text'].strip()}' — 수치는 Fact로 연결하고, 명칭 속 숫자는 [[ ]]로 표시하세요")
    return parts, fact_ids, issues


def claim_out(c: Claim) -> dict:
    text = "".join(p.get("display") or p.get("text") or "" for p in c.parts)
    return {"id": c.id, "material_id": c.material_id, "kind": c.kind, "parts": c.parts, "text": text,
            "fact_ids": c.fact_ids, "evidence_ids": c.evidence_ids, "author": c.author,
            "review_status": c.review_status, "stale_reason": c.stale_reason, "version": c.version, "quote": c.quote,
            "issues": [f"근거 없는 숫자: '{p['text'].strip()}'" for p in c.parts if p["type"] == "text" and _unbound_digit(p["text"])]}


class ClaimIn(BaseModel):
    kind: Literal["fact", "interpretation", "recommendation"]
    text: str = Field(min_length=1, max_length=400)
    quote: Optional[str] = Field(default=None, max_length=600)  # set when the sentence came from an AI suggestion
    accept: bool = False  # the person picked it: adopt right away


@router.post("/materials/{material_id}/claims", status_code=201)
def create_claim(material_id: str, body: ClaimIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    parts, fact_ids, issues = parse_claim_text(db, m.project_id, body.text)
    if any(i.startswith("없는 Fact") for i in issues):
        raise ApiError(422, "INVALID_FACT", "; ".join(issues))
    c = Claim(id=new_id("CL"), project_id=m.project_id, material_id=m.id, kind=body.kind, parts=parts,
              evidence_ids=[m.id], fact_ids=fact_ids, author="ai" if body.quote else "user", quote=body.quote,
              review_status="accepted" if body.accept and not issues else "pending")
    db.add(c)
    audit(db, m.project_id, "claim", c.id, "create", after={"kind": body.kind, "text": body.text}, actor=who)
    db.commit()
    return claim_out(c)


class ClaimPatch(BaseModel):
    base_version: int
    kind: Optional[Literal["fact", "interpretation", "recommendation"]] = None
    text: Optional[str] = None
    review_status: Optional[Literal["pending", "accepted", "excluded"]] = None


@router.patch("/claims/{claim_id}")
def patch_claim(claim_id: str, body: ClaimPatch, db: Session = Depends(get_db), who: str = Depends(actor)):
    c = db.get(Claim, claim_id)
    if c is None:
        raise not_found("근거 문장")
    if body.base_version != c.version:
        raise stale_version(c.version, claim_out(c))
    before = claim_out(c)
    if body.text is not None:
        parts, fact_ids, issues = parse_claim_text(db, c.project_id, body.text)
        if any(i.startswith("없는 Fact") for i in issues):
            raise ApiError(422, "INVALID_FACT", "; ".join(issues))
        c.parts, c.fact_ids = parts, fact_ids
        if c.review_status == "accepted" and body.review_status is None:
            c.review_status = "pending"  # edited text needs a fresh decision
    if body.kind:
        c.kind = body.kind
    if body.review_status:
        if body.review_status == "accepted":
            issues = claim_out(c)["issues"]
            if issues:
                raise ApiError(422, "UNBOUND_NUMBER", issues[0], "숫자를 Fact로 연결하거나 문장에서 제거하세요")
            for fid in c.fact_ids:
                row = db.scalar(select(FactRow).where(FactRow.project_id == c.project_id, FactRow.fact_id == fid))
                if row is None or row.superseded_by:
                    raise ApiError(422, "INVALID_FACT", "연결된 수치가 수정되어 새 버전으로 바뀌었습니다", "문장의 수치를 다시 연결하세요")
        c.review_status = body.review_status
        c.stale_reason = None if body.review_status == "accepted" else c.stale_reason
    c.version += 1
    audit(db, c.project_id, "claim", c.id, "update", before=before, after=claim_out(c), actor=who)
    db.commit()
    return claim_out(c)


# ------------------------------------------------------------------ manual facts

def fact_out(row: FactRow) -> dict:
    f = Fact.model_validate(row.data)
    fmt = UNIT_FORMATTER.get(f.unit, "int")
    return {"id": row.fact_id, "origin": row.origin, "metric": f.metric, "label": f.label, "brand_id": f.brand_id,
            "entity": f.entity, "value": str(f.value) if f.value is not None else None, "unit": f.unit,
            "display": format_value(fmt, f.value) if f.value is not None else None, "measured_at": f.measured_at,
            "dims": f.dims, "period_start": f.period_start, "period_end": f.period_end, "source": f.source,
            "verification_status": row.verification_status, "superseded_by": row.superseded_by,
            "review_note": row.review_note, "token": "{{" + row.fact_id + "}}"}


@router.get("/projects/{project_id}/facts")
def list_facts(project_id: str, metric: Optional[str] = None, status: Optional[str] = None,
              db: Session = Depends(get_db)):
    """Facts with no material card (e.g. search-index rows from Naver DataLab) — the material-less
    counterpart to a material's embedded `facts` list, so these still have a review surface."""
    get_project(db, project_id)
    q = select(FactRow).where(FactRow.project_id == project_id, FactRow.material_id.is_(None),
                              FactRow.superseded_by.is_(None))
    if status:
        q = q.where(FactRow.verification_status == status)
    rows = [fact_out(r) for r in db.scalars(q.order_by(FactRow.created_at))]
    if metric:
        rows = [r for r in rows if r["metric"] == metric]
    return rows


class ManualFactIn(BaseModel):
    metric: str
    label: Optional[str] = None
    value: str
    measured_at: date


@router.post("/materials/{material_id}/facts", status_code=201)
def create_manual_fact(material_id: str, body: ManualFactIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    m = get_material(db, material_id)
    if body.metric not in MANUAL_METRICS:
        raise ApiError(422, "UNKNOWN_METRIC", f"지원 지표: {', '.join(MANUAL_METRICS)}")
    src = db.get(Source, m.source_id)
    try:
        f = make_manual_fact(brand_id=m.brand_id or "-", entity=m.entity or m.title, metric=body.metric, value=body.value,
                             measured_at=body.measured_at, source=src.title, source_id=src.id, evidence_id=m.id,
                             label=body.label, url=src.original_url)
    except ValueError as exc:
        raise ApiError(422, "INVALID_VALUE", str(exc))
    exists = db.scalar(select(FactRow).where(FactRow.project_id == m.project_id, FactRow.fact_id == f.id))
    if exists:
        return fact_out(exists)
    row = FactRow(project_id=m.project_id, fact_id=f.id, origin="manual", material_id=m.id,
                  research_item_id=m.research_item_id, data=json.loads(f.model_dump_json()), verification_status="candidate")
    db.add(row)
    audit(db, m.project_id, "fact", f.id, "create", after=body.model_dump(mode="json"), actor=who)
    db.commit()
    return fact_out(row)


class FactReview(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value: Optional[str] = None
    note: Optional[str] = None


@router.patch("/facts/{fact_id}/review")
def review_fact(fact_id: str, body: FactReview, project_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    row = db.scalar(select(FactRow).where(FactRow.project_id == project_id, FactRow.fact_id == fact_id))
    if row is None or row.superseded_by:
        raise not_found("Fact")
    if row.origin not in ("manual", "auto"):
        raise ApiError(409, "INVALID_STATE", "CSV·게시물 수치는 배치 단위로 채택합니다")
    if body.action == "confirm":
        row.verification_status = "eligible"
    elif body.action == "reject":
        if not (body.note or "").strip():
            raise ApiError(422, "REASON_REQUIRED", "제외 사유를 입력하세요")
        row.verification_status = "rejected"
    else:
        if body.value is None or not (body.note or "").strip():
            raise ApiError(422, "REASON_REQUIRED", "수정값과 수정 사유를 입력하세요")
        old = Fact.model_validate(row.data)
        try:
            new = make_manual_fact(brand_id=old.brand_id, entity=old.entity, metric=old.metric, value=body.value,
                                   measured_at=old.measured_at, source=old.source, source_id=old.source_id,
                                   evidence_id=old.evidence_id, label=old.label, url=old.url, status="candidate")
        except ValueError as exc:
            raise ApiError(422, "INVALID_VALUE", str(exc))
        new_row = FactRow(project_id=project_id, fact_id=new.id, origin=row.origin, material_id=row.material_id,
                          research_item_id=row.research_item_id, data=json.loads(new.model_dump_json()),
                          verification_status="eligible", review_note=body.note)
        db.add(new_row)
        row.superseded_by = new.id
        # Dependent claims become stale until re-linked and reviewed (PRD A16).
        for c in db.scalars(select(Claim).where(Claim.project_id == project_id)):
            if fact_id in (c.fact_ids or []):
                c.review_status, c.stale_reason = "stale", f"연결된 수치가 수정되었습니다({body.note})"
        audit(db, project_id, "fact", fact_id, "correct", before=str(old.value), after=body.value, reason=body.note, actor=who)
        db.commit()
        return fact_out(new_row)
    row.review_note = body.note
    audit(db, project_id, "fact", fact_id, body.action, reason=body.note, actor=who)
    db.commit()
    return fact_out(row)
