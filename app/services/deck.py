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
from core.rendering.compress import compress_image
from core.rendering.pptx_renderer import render_deck
from core.rendering.preview import RenderUnavailable, render_pages
from core.schemas.slidespec import DeckSpec

SEOUL = ZoneInfo("Asia/Seoul")


def _resolver(result):
    def resolve(asset_id: str):
        a = result.assets[asset_id]
        return a.path, a.width, a.height
    return resolve


def _light_resolver(result, cache_dir: Path):
    """Same AssetResolver contract as _resolver, but each image is compressed once (cached by
    asset_id) and the *compressed* file's own dimensions are returned — the renderer's crop math
    only ever sees fractions of whatever file it is actually about to embed."""
    cache: dict[str, tuple[str, int, int]] = {}

    def resolve(asset_id: str):
        hit = cache.get(asset_id)
        if hit:
            return hit
        a = result.assets[asset_id]
        dest = cache_dir / f"{asset_id}.jpg"
        w, h = compress_image(Path(a.path), dest)
        cache[asset_id] = (str(dest), w, h)
        return cache[asset_id]
    return resolve


def current_fingerprint(db: Session, project: Project) -> str:
    return fingerprint(load_inputs(db, project))


def _recollect_missing(db: Session, project: Project, progress: Callable[[int], None]) -> None:
    """Phase 3-5: 만들기 전에, 원인이 "수집 필요"인 빠진 장표만 한 번 더 자동으로 수집을 시도한다
    (기존 "빠진 자료 다시 모으기"와 같은 경로 — item_ids를 모아 research_run을 한 번 돌릴 뿐)."""
    from app.jobs import create_job
    from app.services import missing
    from app.services.research import run_research
    from core.schemas.project import Project as CoreProject

    inputs = load_inputs(db, project)
    result = build_deck(inputs)
    core = CoreProject.model_validate(project.config)
    missing.annotate(db, project, core, result.deck.plan)
    item_ids = sorted({iid for s in result.deck.plan if s.cause == "collect" for iid in (s.item_ids or [])})
    if not item_ids:
        return
    job, _ = create_job(db, project.id, project.version, "research_run", {"item_ids": item_ids})
    run_research(db, job, lambda pct: progress(10 + pct // 10))  # 0~10%만 이 단계에 배정 (끝에서 db.expire_all())


def _write_slides(db: Session, project: Project, job: Job, progress: Callable[[int], None]) -> dict:
    """P3-4~: AI가 장마다 헤드라인(주장 + 근거)을 쓴다. 장 본문이 그대로면 예전 글을 다시 쓰고, AI를 못 부르면
    규칙 문장으로 만든다 — 덱 만들기 자체는 멈추지 않는다."""
    from app.services import insights
    from integrations.base import ProviderError

    try:
        return insights.write_slides(db, project, job.id, lambda pct: progress(10 + pct // 20))
    except ProviderError as exc:
        db.rollback()
        return {"error": exc.code}


def _ensure_synthesis(db: Session, project: Project) -> dict:
    """P3-7: generate the default insight pages once per body fingerprint; AI failure never blocks a deck."""
    from app.config import settings
    from app.services import synthesis
    from integrations.base import ProviderError

    if not settings.provider_configured("anthropic"):
        return {"skipped": "provider_not_configured"}
    try:
        return synthesis.ensure_default(db, project)
    except ProviderError as exc:
        return {"error": exc.code}


def _ensure_diagnosis(db: Session, project: Project, job: Job) -> dict:
    """P5-1: 자사 브랜드마다 진단을 쓴다 — 채택 자료가 그대로면 예전 진단을 쓰고, AI를 못 부르면 건너뛴다."""
    from app.services import diagnosis
    from integrations.base import ProviderError

    if not diagnosis.ai_ready():
        return {"skipped": "provider_not_configured"}
    try:
        return diagnosis.ensure(db, project, job.id)
    except ProviderError as exc:
        db.rollback()
        return {"error": exc.code}


@register("deck_build")
def run_build(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    project = db.get(Project, job.project_id)
    deck = db.get(Deck, job.params["deck_id"])
    _recollect_missing(db, project, progress)
    writing = _write_slides(db, project, job, progress)
    synthesis = _ensure_synthesis(db, project)
    diagnosis = _ensure_diagnosis(db, project, job)
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
            "render_status": deck.render_status, "writing": writing, "synthesis": synthesis,
            "diagnosis": diagnosis}


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
        # 경량 PPTX 옵션 (09_고객피드백_요구사항화.md): same slides, every image resized+JPEG — an
        # additional file in the bundle, never a replacement for the full-quality report.pptx.
        light_path = out / "report_light.pptx"
        render_deck(result.deck, light_path, _light_resolver(result, out / "light_assets"))
        paths["pptx_light"] = light_path
        manifest = {}
        for name, p in paths.items():
            key = f"{key_dir}/{p.name}"
            storage.put_file(key, p)
            manifest[p.name] = key
        light_bytes = light_path.stat().st_size
    exp = Export(id=export_id, project_id=project.id, deck_id=deck.id, deck_version=deck.version, qc=qc.to_dict(),
                 manifest=manifest)
    db.add(exp)
    db.commit()
    return {"export_id": export_id, "files": sorted(manifest), "light_pptx_bytes": light_bytes,
            "light_pptx_under_30mb": light_bytes <= 30 * 1024 * 1024}
