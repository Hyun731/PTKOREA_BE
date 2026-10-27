"""Deck build and export jobs (PRD 11, 12; DEVELOPMENT_PLAN 단계 1)."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.jobs import JobFailure, register
from app.models import Deck, Export, Job, Project, new_id
from app.services.inputs import load_inputs
from app.storage import get_storage
from core.composition.build import build_deck, fingerprint
from core.export import write_outputs
from core.quality.qc import run_qc, self_brand_names
from core.rendering.pptx_renderer import render_deck
from core.rendering.preview import RenderUnavailable, render_pages
from core.schemas.slidespec import DeckSpec

SEOUL = ZoneInfo("Asia/Seoul")


def _resolver(result):
    def resolve(asset_id: str):
        a = result.assets[asset_id]
        return a.path, a.width, a.height
    return resolve


def current_fingerprint(db: Session, project: Project) -> str:
    return fingerprint(load_inputs(db, project))


@register("deck_build")
def run_build(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    project = db.get(Project, job.project_id)
    deck = db.get(Deck, job.params["deck_id"])
    inputs = load_inputs(db, project)
    inputs.deck_id, inputs.deck_version = deck.id, deck.version
    inputs.generated_on = deck.created_at.astimezone(SEOUL).date()
    progress(15)
    result = build_deck(inputs)
    qc = run_qc(result.deck, result.metrics.registry, lambda aid: result.assets.get(aid), self_brand_names(project.config))
    progress(35)
    storage = get_storage()
    key_dir = f"decks/{project.id}/{deck.id}"
    pptx_key = f"{key_dir}/report.pptx"
    render_deck(result.deck, storage.path(pptx_key), _resolver(result))
    deck.spec = json.loads(result.deck.model_dump_json())
    deck.qc = qc.to_dict()
    deck.fingerprint = result.deck.input_fingerprint
    deck.pptx_key = pptx_key
    db.commit()
    progress(55)
    # Final preview = the generated PPTX rendered by LibreOffice, never an HTML capture.
    try:
        pages = render_pages(storage.path(pptx_key), storage.path(f"{key_dir}/preview"))
        deck.preview_keys = [f"{key_dir}/preview/{p.name}" for p in pages]
        deck.render_status = "ok" if len(pages) == len(result.deck.slides) else "failed"
        if deck.render_status == "failed":
            deck.render_message = f"렌더 페이지 수 불일치({len(pages)}≠{len(result.deck.slides)})"
    except RenderUnavailable as exc:
        deck.render_status, deck.render_message = "unavailable", str(exc)[:400]
    deck.status = "ready"  # only after the real-render preview exists (or is known unavailable)
    db.commit()
    return {"deck_id": deck.id, "deck_version": deck.version, "qc_blocks": qc.blocks, "qc_warns": qc.warns,
            "render_status": deck.render_status}


def next_deck_version(db: Session, project_id: str) -> int:
    return (db.scalar(select(func.max(Deck.version)).where(Deck.project_id == project_id)) or 0) + 1


@register("export")
def run_export(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    project = db.get(Project, job.project_id)
    deck = db.get(Deck, job.params["deck_id"])
    inputs = load_inputs(db, project)
    if fingerprint(inputs) != deck.fingerprint:
        raise JobFailure("STALE_VERSION", "덱 생성 이후 자료·검토 상태가 바뀌었습니다. 다시 생성한 뒤 내보내세요")
    inputs.deck_id, inputs.deck_version = deck.id, deck.version
    inputs.generated_on = deck.created_at.astimezone(SEOUL).date()
    result = build_deck(inputs)
    stored = json.loads(DeckSpec.model_validate(deck.spec).model_dump_json())  # fills fields added since the build
    if json.loads(result.deck.model_dump_json()) != stored:
        raise JobFailure("RENDER_FAILED", "재현한 덱이 미리보기 버전과 다릅니다")
    qc = run_qc(result.deck, result.metrics.registry, lambda aid: result.assets.get(aid), self_brand_names(project.config))
    if qc.blocks:
        raise JobFailure("QC_BLOCKED", f"QC 차단 {qc.blocks}건 — 출력 화면에서 해결하세요")
    if deck.render_status != "ok":
        raise JobFailure("RENDER_FAILED", "실제 PPTX 렌더 미리보기를 확인할 수 없어 확정 출력을 막았습니다")
    progress(40)
    storage = get_storage()
    export_id = new_id("EXP")
    key_dir = f"exports/{project.id}/{export_id}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        paths = write_outputs(result, qc, out, render_pptx=False,
                              versions={"deck_id": deck.id, "project_version": project.version})
        # The client deck is the exact file that was previewed for this deck_version.
        shutil.copyfile(storage.path(deck.pptx_key), out / "report.pptx")
        paths["pptx"] = out / "report.pptx"
        manifest = {}
        for name, p in paths.items():
            key = f"{key_dir}/{p.name}"
            storage.put_file(key, p)
            manifest[p.name] = key
    exp = Export(id=export_id, project_id=project.id, deck_id=deck.id, deck_version=deck.version, qc=qc.to_dict(),
                 manifest=manifest)
    db.add(exp)
    db.commit()
    return {"export_id": export_id, "files": sorted(manifest)}
