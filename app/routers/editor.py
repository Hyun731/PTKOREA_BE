"""Deck editor: editable copy of a generated deck, AI edit requests, export of the edited copy."""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError, not_found, stale_version
from app.models import EditLog, new_id, utcnow
from app.routers.decks import export_out, get_deck
from app.routers.projects import actor, get_project
from app.services import editor as svc
from app.services.audit import audit
from app.services.deck import current_fingerprint
from core.composition.tokens import FONTS_DIR
from core.editing.scope import SelectionIn
from core.schemas.slidespec import SlideSpec
from integrations.base import ProviderError

router = APIRouter()


def _ready(db: Session, deck_id: str):
    d = get_deck(db, deck_id)
    if d.status != "ready" or not d.spec:
        raise ApiError(409, "INVALID_STATE", "초안 생성이 끝난 덱만 편집할 수 있습니다")
    return d


def _slides(raw: list[dict]) -> list[SlideSpec]:
    try:
        slides = [SlideSpec.model_validate(s) for s in raw]
    except ValidationError as exc:
        raise ApiError(422, "INVALID_INPUT", f"슬라이드 형식 오류: {str(exc)[:240]}")
    ids = [s.slide_id for s in slides]
    if len(ids) != len(set(ids)):
        raise ApiError(422, "INVALID_INPUT", "슬라이드 id가 중복됩니다")
    for s in slides:
        bids = [b.block_id for b in s.blocks]
        if len(bids) != len(set(bids)):
            raise ApiError(422, "INVALID_INPUT", f"{s.slide_id}에 중복된 요소 id가 있습니다")
    return slides


def edit_out(db: Session, d, slides: Optional[list[SlideSpec]] = None) -> dict:
    p = get_project(db, d.project_id)
    slides = slides if slides is not None else svc.edit_slides(d, db)
    return {"deck_id": d.id, "deck_version": d.version, "project_id": p.id, "project_name": p.name,
            "title": d.edit_title or f"{p.name}_v{d.version}", "edit_version": d.edit_version, "edited": d.edit_slides is not None,
            "edited_at": d.edited_at, "stale": d.fingerprint != current_fingerprint(db, p),
            "slides": [s.model_dump(mode="json") for s in slides], "qc": svc.qc_for(db, p, d, slides),
            "ai": {"available": svc.ai_available(), "modes": ["claude", "mock"] if svc.ai_available() else ["mock"]}}


@router.get("/decks/{deck_id}/edit")
def read_edit(deck_id: str, db: Session = Depends(get_db)):
    return edit_out(db, _ready(db, deck_id))


class EditIn(BaseModel):
    base_version: int
    slides: list[dict]
    title: Optional[str] = Field(default=None, max_length=200)


def _store(db: Session, d, base_version: int, raw: list[dict], title: Optional[str], who: str, what: str) -> list[SlideSpec]:
    if base_version != d.edit_version:
        raise stale_version(d.edit_version)
    slides = _slides(raw)
    if not slides:
        raise ApiError(422, "INVALID_INPUT", "슬라이드가 최소 1장 있어야 합니다")
    d.edit_slides = [s.model_dump(mode="json") for s in slides]
    if title is not None:
        d.edit_title = title.strip() or None
    d.edit_version += 1
    d.edited_at = utcnow()
    audit(db, d.project_id, "deck", d.id, what, after={"edit_version": d.edit_version, "slides": len(slides)}, actor=who)
    return slides


@router.put("/decks/{deck_id}/edit")
def save_edit(deck_id: str, body: EditIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    d = _ready(db, deck_id)
    slides = _store(db, d, body.base_version, body.slides, body.title, who, "edit_save")
    db.commit()
    p = get_project(db, d.project_id)
    return {"edit_version": d.edit_version, "edited_at": d.edited_at, "qc": svc.qc_for(db, p, d, slides)}


@router.delete("/decks/{deck_id}/edit")
def reset_edit(deck_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    d = _ready(db, deck_id)
    before = [s.model_dump(mode="json") for s in svc.edit_slides(d, db)] if d.edit_slides is not None else None
    d.edit_slides, d.edited_at = None, utcnow()
    d.edit_version += 1
    if before is not None:  # going back to the draft is itself undoable from the history
        db.add(EditLog(id=new_id("EL"), project_id=d.project_id, deck_id=d.id, kind="reset", status="applied",
                       message="초안으로 되돌리기", actor=who, slides_before=before, edit_version=d.edit_version,
                       decided_at=utcnow()))
    audit(db, d.project_id, "deck", d.id, "edit_reset", actor=who)
    db.commit()
    return edit_out(db, d)


class QcIn(BaseModel):
    slides: list[dict]


@router.post("/decks/{deck_id}/edit/qc")
def check_edit(deck_id: str, body: QcIn, db: Session = Depends(get_db)):
    d = _ready(db, deck_id)
    return svc.qc_for(db, get_project(db, d.project_id), d, _slides(body.slides))


class AiIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    slides: list[dict]
    current_slide_id: str
    scope: Literal["selection", "slide", "deck"] = "slide"
    selection: SelectionIn = SelectionIn()
    history: list[dict] = []
    mode: Literal["auto", "claude", "mock"] = "auto"


@router.post("/decks/{deck_id}/edit/ai")
def ai_edit(deck_id: str, body: AiIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    d = _ready(db, deck_id)
    p = get_project(db, d.project_id)
    slides = _slides(body.slides)
    if body.current_slide_id not in {s.slide_id for s in slides}:
        raise ApiError(422, "INVALID_INPUT", "현재 슬라이드가 덱에 없습니다")
    if body.mode == "claude" and not svc.ai_available():
        raise ApiError(503, "PROVIDER_NOT_CONFIGURED", "Anthropic 키·모델이 설정되지 않았습니다", "Mock 모드로 시도하세요")
    try:
        out = svc.plan_edit(db, p, d, slides=slides, current_slide_id=body.current_slide_id, scope=body.scope,
                            selection=body.selection, message=body.message, history=body.history, mode=body.mode)
    except ProviderError as exc:
        status = {"BUDGET_EXCEEDED": 409, "RATE_LIMITED": 429}.get(exc.code, 502)
        raise ApiError(status, exc.code, str(exc), "잠시 뒤 다시 시도하거나 Mock 모드를 쓰세요")
    log = EditLog(id=new_id("EL"), project_id=p.id, deck_id=d.id, kind="ai",
                  status="proposed" if out["applied"] else "cancelled", message=body.message, reply=out["reply"],
                  mode=out["mode"], scope=body.scope, slide_ids=sorted(out["changed"]),
                  summary={"applied": out["applied"], "rejected": out["rejected"]},
                  cost_usd=(out.get("usage") or {}).get("cost_usd") or 0.0, actor=who,
                  decided_at=None if out["applied"] else utcnow())
    db.add(log)
    audit(db, p.id, "deck", d.id, "edit_ai", after={"mode": out["mode"], "scope": body.scope, "applied": len(out["applied"]),
                                                     "rejected": len(out["rejected"]), "log_id": log.id}, actor=who)
    db.commit()
    return {**out, "log_id": log.id}


def short_id(log_id: str) -> str:
    """Commit-hash style handle shown in the history: EL-3f9a2c41b0de -> 3f9a2c4."""
    return log_id.split("-", 1)[-1][:7]


def log_out(e: EditLog) -> dict:
    return {"id": e.id, "short": short_id(e.id), "restored_from_short": short_id(e.restored_from) if e.restored_from else None,
            "kind": e.kind, "status": e.status, "message": e.message, "reply": e.reply, "mode": e.mode,
            "scope": e.scope, "slide_ids": e.slide_ids, "applied": (e.summary or {}).get("applied", []),
            "rejected": (e.summary or {}).get("rejected", []), "cost_usd": e.cost_usd, "actor": e.actor,
            "edit_version": e.edit_version, "restored_from": e.restored_from, "created_at": e.created_at,
            "decided_at": e.decided_at, "can_restore_after": e.slides_after is not None,
            "can_restore_before": e.slides_before is not None}


def _log(db: Session, deck_id: str, log_id: str) -> EditLog:
    e = db.get(EditLog, log_id)
    if e is None or e.deck_id != deck_id:
        raise not_found("편집 기록")
    return e


@router.get("/decks/{deck_id}/edit/log")
def list_log(deck_id: str, db: Session = Depends(get_db)):
    _ready(db, deck_id)
    rows = db.scalars(select(EditLog).where(EditLog.deck_id == deck_id).order_by(EditLog.created_at.desc()).limit(200))
    return [log_out(e) for e in rows]


class ApplyIn(BaseModel):
    base_version: int
    slides_before: list[dict]  # the editor copy the proposal was made on (with unsaved hand edits)
    slides: list[dict]  # the same copy with the proposal merged in
    title: Optional[str] = Field(default=None, max_length=200)


@router.post("/decks/{deck_id}/edit/log/{log_id}/apply")
def apply_log(deck_id: str, log_id: str, body: ApplyIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    d = _ready(db, deck_id)
    e = _log(db, deck_id, log_id)
    if e.status != "proposed":
        raise ApiError(409, "INVALID_STATE", "이미 적용했거나 취소한 수정안입니다")
    before = [s.model_dump(mode="json") for s in _slides(body.slides_before)]
    slides = _store(db, d, body.base_version, body.slides, body.title, who, "edit_ai_apply")
    e.status, e.decided_at, e.edit_version = "applied", utcnow(), d.edit_version
    e.slides_before, e.slides_after = before, d.edit_slides
    db.commit()
    p = get_project(db, d.project_id)
    return {"edit_version": d.edit_version, "edited_at": d.edited_at, "qc": svc.qc_for(db, p, d, slides), "log": log_out(e)}


@router.post("/decks/{deck_id}/edit/log/{log_id}/cancel")
def cancel_log(deck_id: str, log_id: str, db: Session = Depends(get_db)):
    e = _log(db, deck_id, log_id)
    if e.status == "proposed":
        e.status, e.decided_at = "cancelled", utcnow()
        db.commit()
    return log_out(e)


class RestoreIn(BaseModel):
    base_version: int
    to: Literal["after", "before"] = "after"


@router.post("/decks/{deck_id}/edit/log/{log_id}/restore")
def restore_log(deck_id: str, log_id: str, body: RestoreIn, db: Session = Depends(get_db), who: str = Depends(actor)):
    """Go back to the editor copy right after (or right before) a logged change. The restore is logged
    with what it replaced, so it can be undone the same way."""
    d = _ready(db, deck_id)
    e = _log(db, deck_id, log_id)
    snap = e.slides_after if body.to == "after" else e.slides_before
    if snap is None:
        raise ApiError(409, "NO_SNAPSHOT", "이 기록에는 되돌릴 시점이 없습니다")
    current = [s.model_dump(mode="json") for s in svc.edit_slides(d, db)]
    _store(db, d, body.base_version, snap, None, who, "edit_restore")
    when = "직후로" if body.to == "after" else "직전으로"
    label = e.message if e.kind == "ai" else {"reset": "초안으로 되돌리기", "restore": "되돌리기"}.get(e.kind, e.kind)
    r = EditLog(id=new_id("EL"), project_id=d.project_id, deck_id=d.id, kind="restore", status="applied",
                message=f"#{short_id(e.id)} '{label[:60]}' {when} 되돌림", actor=who, slides_before=current, slides_after=d.edit_slides,
                edit_version=d.edit_version, restored_from=e.id, decided_at=utcnow())
    db.add(r)
    db.commit()
    return {**edit_out(db, d), "log": log_out(r)}


@router.get("/decks/{deck_id}/edit/assets")
def edit_assets(deck_id: str, db: Session = Depends(get_db)):
    d = _ready(db, deck_id)
    return svc.asset_choices(db, get_project(db, d.project_id))


@router.post("/decks/{deck_id}/edit/export", status_code=201)
def export_edit(deck_id: str, db: Session = Depends(get_db), who: str = Depends(actor)):
    d = _ready(db, deck_id)
    p = get_project(db, d.project_id)
    if d.fingerprint != current_fingerprint(db, p):
        raise ApiError(409, "STALE_VERSION", "덱 생성 이후 자료·검토 상태가 바뀌었습니다",
                       "편집 내용은 남아 있지만, 수치가 최신 자료와 다를 수 있습니다. 초안을 다시 만든 뒤 편집하세요")
    exp = svc.export_edited(db, p, d)
    audit(db, p.id, "deck", d.id, "edit_export", after={"export_id": exp.id, "edit_version": d.edit_version}, actor=who)
    db.commit()
    return export_out(exp)


FONT = re.compile(r"^Pretendard-[A-Za-z]+\.otf$")


@router.get("/fonts/{name}")
def font_file(name: str):
    path = FONTS_DIR / name
    if not FONT.match(name) or not path.exists():
        raise not_found("글꼴")
    return FileResponse(path, media_type="font/otf", headers={"Cache-Control": "public, max-age=604800"})
