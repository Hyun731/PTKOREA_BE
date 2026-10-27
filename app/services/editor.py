"""Deck editor service: the editable copy of a generated deck, QC on it, AI edit requests, export.

The generated `Deck.spec` never changes. The editor copy (`Deck.edit_slides`) starts as a copy of
it and is what the editor shows, saves and exports. QC runs on the copy with the same rules as a
generated deck, so an edit cannot export a number without evidence.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Deck, Export, Project, new_id, utcnow
from app.services.inputs import load_inputs
from app.storage import get_storage
from core.composition.build import BuildResult, build_deck, fingerprint
from core.composition.tokens import tokens
from core.editing import mock
from core.editing.commands import OPS, apply_commands
from core.editing.scope import Scope, SelectionIn, Target, resolve_target, slide_context
from core.editing.text import DeckVocabulary
from core.export import write_outputs
from core.quality.qc import FORBIDDEN_WORDS, run_qc, self_brand_names
from core.rendering.pptx_renderer import render_deck
from core.schemas.slidespec import DeckSpec, SlideSpec
from integrations.base import ProviderError

_CACHE: dict[tuple[str, str], BuildResult] = {}
_LOCK = threading.Lock()


def build_context(db: Session, project: Project) -> BuildResult:
    """Fact registry + assets for QC on edited slides; cached per input fingerprint."""
    inputs = load_inputs(db, project)
    key = (project.id, fingerprint(inputs))
    with _LOCK:
        hit = _CACHE.get(key)
    if hit:
        return hit
    result = build_deck(inputs)
    with _LOCK:
        for k in [k for k in _CACHE if k[0] == project.id]:
            _CACHE.pop(k)
        _CACHE[key] = result
    return result


def base_slides(deck: Deck) -> list[SlideSpec]:
    return [SlideSpec.model_validate(s) for s in (deck.spec or {}).get("slides", [])]


def edit_slides(deck: Deck, db: Optional[Session] = None) -> list[SlideSpec]:
    if deck.edit_slides is not None:
        return [SlideSpec.model_validate(s) for s in deck.edit_slides]
    slides = base_slides(deck)
    if db is not None:
        carry_notes(db, deck, slides)
    return slides


def carry_notes(db: Session, deck: Deck, slides: list[SlideSpec]) -> int:
    """A rebuilt draft starts from the previous draft's speaker notes (same slide id): rebuilding to pick
    up new material must not throw away the presenter's script."""
    from sqlalchemy import select
    prev = db.scalars(select(Deck).where(Deck.project_id == deck.project_id, Deck.version < deck.version,
                                         Deck.edit_slides.is_not(None)).order_by(Deck.version.desc())).first()
    if prev is None:
        return 0
    notes = {s.get("slide_id"): s.get("speaker_notes") for s in prev.edit_slides if s.get("speaker_notes")}
    n = 0
    for s in slides:
        if not s.speaker_notes and notes.get(s.slide_id):
            s.speaker_notes = notes[s.slide_id]
            n += 1
    return n


def edited_deck(deck: Deck, slides: list[SlideSpec]) -> DeckSpec:
    spec = DeckSpec.model_validate(deck.spec)
    return spec.model_copy(update={"slides": renumber(slides)})


def renumber(slides: list[SlideSpec]) -> list[SlideSpec]:
    """Page numbers follow the editor order (slides can be added, removed and moved)."""
    out = []
    for i, s in enumerate(slides, start=1):
        s = s.model_copy(deep=True)
        s.page_no = i
        for b in s.blocks:
            if getattr(b, "role", None) == "page_no" and b.paragraphs and b.paragraphs[0].parts:
                b.paragraphs[0].parts[0].text = str(i)
        out.append(s)
    return out


def qc_for(db: Session, project: Project, deck: Deck, slides: list[SlideSpec]) -> dict:
    result = build_context(db, project)
    report = run_qc(edited_deck(deck, slides), result.metrics.registry, lambda aid: result.assets.get(aid),
                     self_brand_names(project.config))
    return report.to_dict()


def asset_choices(db: Session, project: Project) -> list[dict]:
    result = build_context(db, project)
    return [{"id": a.id, "title": a.title, "width": a.width, "height": a.height, "review_status": a.review_status}
            for a in result.assets.values()]


# ------------------------------------------------------------------ AI edit

COMMAND_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reply", "commands"],
    "properties": {
        "reply": {"type": "string"},
        "commands": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["op", "slide_id", "reason", "args"],
            "properties": {
                "op": {"type": "string", "enum": OPS},
                "slide_id": {"type": "string"},
                "reason": {"type": "string"},
                # Op-specific fields as one JSON object string (the strict schema caps union fields);
                # the command models validate it on our side.
                "args": {"type": "string"},
            }}},
    },
}

SYSTEM = """당신은 브랜드 마케팅 팩트북(PowerPoint) 편집기 안의 AI 편집 도우미입니다.
사용자의 요청을 슬라이드 요소에 대한 '편집 명령' 목록으로 바꿉니다. 슬라이드를 새로 만들지 않고, 기존 요소 id를 유지한 채 필요한 부분만 고칩니다.

캔버스: 1280×720 단위(좌상단 0,0). 글자 크기는 pt.
명령(op):
- update_text: element_id, paragraphs(문단별 문자열 배열) — 텍스트 요소만
- update_style: element_id + size / color / weight(light·regular·semibold·bold·heavy) / align(l·c·r) / fill / line_spacing 중 바꿀 것만
- move_element: element_id, x, y
- resize_element: element_id, w, h (+ 선택적으로 x, y)
- add_element: element{kind: text|shape|image, x, y, w, h, paragraphs, size, color, fill, shape, asset_id}
- delete_element: element_id
- reorder_elements: element_id, to(front·back·forward·backward)
- update_background: color (null이면 배경 제거)
- restructure_layout: items[{element_id, x, y, w, h}] — 여러 요소 배치를 한 번에
- update_notes: text — 발표자 메모(발표 대본). 슬라이드에 보이는 내용과 근거 범위 안에서, 말하듯 자연스럽게. 여기서는 숫자를 써도 되지만 장표에 있는 값만 씁니다.
- rename_slide: title — 슬라이드 이름
각 명령은 {op, slide_id, reason, args}이며 args는 위 필드들을 담은 JSON 객체 문자열입니다(예: "{\"element_id\": \"lead\", \"size\": 20}"). 쓰지 않는 필드는 넣지 않습니다.
모든 명령에 reason(한국어 한 문장, 왜 바꾸는지)을 씁니다.

텍스트 규칙(근거 보존 — 반드시 지킴):
- paragraphs는 아래 토큰 문법을 씁니다. {{F-…}}·{{DF-…}} 수치 칩, {{p:N}} 원래 문장의 날짜·이름·링크 조각, [[이름]] 고정 이름, **굵게**.
- 숫자를 일반 텍스트로 쓰지 않습니다. 숫자는 이 덱에 이미 있는 수치 칩(usable_facts)으로만 넣습니다. 새 수치를 지어내지 않습니다.
- 원래 문장에 있던 사실을 바꾸거나 과장하지 않습니다. 요약·다듬기는 원래 내용 범위 안에서만.
- 금지어: """ + ", ".join(FORBIDDEN_WORDS) + """

범위 규칙:
- editable_element_ids가 목록이면 그 요소만 고칩니다. areas가 있으면 그 영역 안에만 새 요소를 추가할 수 있습니다.
- 대상 슬라이드 밖은 건드리지 않습니다.
- 색은 #RRGGBB 또는 디자인 토큰 이름(아래)을 씁니다. 디자인은 기존 톤(남색 122648 중심)과 어울리게.

reply에는 무엇을 어떻게 바꾸는지 한국어 1~3문장으로 씁니다. 바꿀 수 없는 요청이면 commands를 비우고 이유를 reply에 씁니다."""

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def ai_available() -> bool:
    return settings.provider_configured("anthropic")


def _model_prompt(slides: list[SlideSpec], target: Target, current: str, message: str, history: list[dict],
                  vocab: DeckVocabulary) -> str:
    ctx = [slide_context(s, target) for s in slides if s.slide_id in target.slide_ids]
    facts = [{"token": "{{" + fid + "}}", "shows": p.display} for fid, p in list(vocab.facts.items())[:200]]
    colors = {k: v for k, v in tokens()["colors"].items() if k in ("navy", "text", "muted", "subtle", "white", "red", "gold",
                                                                  "green", "tint", "pale", "slate", "link")}
    past = [{"role": h.get("role"), "text": str(h.get("text", ""))[:600]} for h in history[-6:]]
    return json.dumps({"request": message, "current_slide_id": current, "recent_chat": past, "slides": ctx,
                       "usable_facts": facts, "known_names": sorted(vocab.names)[:200], "color_tokens": colors},
                      ensure_ascii=False)


def _clean(cmd: dict) -> dict:
    """Model command {op, slide_id, reason, args: json} -> flat command dict (nulls dropped)."""
    try:
        args = json.loads(cmd.get("args") or "{}")
    except ValueError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    out = {k: v for k, v in {**args, "op": cmd.get("op"), "slide_id": cmd.get("slide_id"), "reason": cmd.get("reason", "")}.items()
           if v is not None}
    if out.get("op") == "restructure_layout":
        out["items"] = [{k: v for k, v in it.items() if v is not None} for it in out.get("items") or []]
    if isinstance(out.get("element"), dict):
        out["element"] = {k: v for k, v in out["element"].items() if v is not None}
    return out


def plan_edit(db: Session, project: Project, deck: Deck, *, slides: list[SlideSpec], current_slide_id: str,
              scope: Scope, selection: SelectionIn, message: str, history: list[dict], mode: str) -> dict:
    target = resolve_target(slides, current_slide_id, scope, selection)
    vocab = DeckVocabulary(slides + base_slides(deck))
    use_model = mode == "claude" or (mode == "auto" and ai_available())
    usage = None
    if use_model:
        from app.services.ledger import RunLedger
        ledger = RunLedger(db, project.id, f"EDIT-{deck.id}"[:40])
        prompt = _model_prompt(slides, target, current_slide_id, message, history, vocab)
        res = ledger.call("anthropic", "editor_edit", {"p": prompt}, 0.25,
                          lambda: _structured()(SYSTEM, prompt, COMMAND_SCHEMA, max_tokens=6000, effort="medium"),
                          cache_days=None)
        reply, raw = res.data.get("reply", ""), [_clean(c) for c in res.data.get("commands", [])]
        usage = {"cost_usd": res.cost_usd, **(res.usage or {})}
    else:
        reply, raw = mock.plan(message, slides, target, current_slide_id)
    allowed, out_of_scope = [], []
    for i, c in enumerate(raw):
        el = c.get("element") if c.get("op") == "add_element" else None
        new_region = None
        if el:
            from core.schemas.slidespec import Region
            new_region = Region(x=el.get("x", 0), y=el.get("y", 0), w=el.get("w", 1), h=el.get("h", 1))
        eids = [it.get("element_id") for it in c.get("items") or []] if c.get("op") == "restructure_layout" else [c.get("element_id")]
        if c.get("op") in ("update_notes", "rename_slide"):  # slide-level, never visible content
            ok = c.get("slide_id") in target.slide_ids
        elif c.get("op") == "update_background":
            ok = c.get("slide_id") in target.slide_ids and not (target.element_ids.get(c.get("slide_id")) and scope == "selection")
        else:
            ok = all(target.allows(c.get("slide_id", ""), e, new_region) for e in eids)
        (allowed if ok else out_of_scope).append(c)
    result = apply_commands(slides, allowed, vocab=vocab)
    rejected = result.rejected + [{"op": c.get("op"), "slide_id": c.get("slide_id"), "element_id": c.get("element_id"),
                                   "reason": "선택한 범위 밖이라 적용하지 않았습니다"} for c in out_of_scope]
    changed_ids = set(result.changed)
    preview = result.slides
    return {
        "mode": "claude" if use_model else "mock",
        "reply": reply,
        "scope": scope,
        "target": {"slide_ids": target.slide_ids,
                   "element_ids": {k: sorted(v - {"__area_only__"}) for k, v in target.element_ids.items()}},
        "commands": allowed,
        "applied": result.applied,
        "rejected": rejected,
        "changed": result.changed,
        "slides": [s.model_dump(mode="json") for s in preview if s.slide_id in changed_ids],
        "qc": qc_for(db, project, deck, preview) if result.applied else None,
        "usage": usage,
    }


# ------------------------------------------------------------------ export

def export_edited(db: Session, project: Project, deck: Deck) -> Export:
    from app.errors import ApiError

    slides = edit_slides(deck, db)
    result = build_context(db, project)
    spec = edited_deck(deck, slides)
    qc = run_qc(spec, result.metrics.registry, lambda aid: result.assets.get(aid), self_brand_names(project.config))
    if qc.blocks:
        raise ApiError(409, "QC_BLOCKED", f"검수 차단 {qc.blocks}건이 있어 내보낼 수 없습니다", "편집기의 검수 목록을 확인하세요",
                       [i for i in qc.to_dict()["issues"] if i["severity"] == "block"])
    storage = get_storage()
    export_id = new_id("EXP")
    key_dir = f"exports/{project.id}/{export_id}"

    def resolve(asset_id: str):
        a = result.assets[asset_id]
        return a.path, a.width, a.height

    edited = dataclasses.replace(result, deck=spec)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        paths = write_outputs(edited, qc, out, render_pptx=False,
                              versions={"deck_id": deck.id, "project_version": project.version, "edit_version": deck.edit_version})
        render_deck(spec, out / "report.pptx", resolve)
        paths["pptx"] = out / "report.pptx"
        manifest = {}
        for _, p in paths.items():
            key = f"{key_dir}/{p.name}"
            storage.put_file(key, p)
            manifest[p.name] = key
    exp = Export(id=export_id, project_id=project.id, deck_id=deck.id, deck_version=deck.version, qc=qc.to_dict(),
                 manifest=manifest, edit_version=deck.edit_version, generated_at=utcnow())
    db.add(exp)
    db.commit()
    return exp
