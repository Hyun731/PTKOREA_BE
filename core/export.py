"""Export bundle (PRD 12 출력 파일): report.pptx, factbook.csv, sources.csv, assets.csv,
findings.json, deck_spec.json, build_report.json, errors.csv. All files are internal review
material except the client deck.
"""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Optional

from core.composition.build import BuildResult
from core.decimalx import ser, ser_strength
from core.quality.qc import QCReport
from core.rendering.pptx_renderer import AssetResolver, render_deck
from core.schemas.facts import DerivedFact, Fact, ImportResult


def _val(v) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return ser(v) or ""
    return str(v)


def _usage(result: BuildResult) -> dict[str, list[str]]:
    used: dict[str, set[str]] = {}
    for s in result.deck.slides:
        for b in s.bindings:
            for fid in [b.fact_id, *result.metrics.registry.lineage(b.fact_id)]:
                used.setdefault(fid, set()).add(s.slide_id)
    return {k: sorted(v) for k, v in used.items()}


def write_factbook(result: BuildResult, path: Path):
    used = _usage(result)
    reg = result.metrics.registry
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["fact_id", "kind", "brand_id", "entity", "metric", "value", "unit", "dims_or_params", "period",
                    "measured_at", "source", "confidence", "verification_status", "formula_id", "derived_from",
                    "used_in", "definition"])
        for f in reg.facts.values():
            w.writerow([f.id, "raw", f.brand_id, f.entity, f.metric, _val(f.value), f.unit,
                        json.dumps(f.dims, ensure_ascii=False), f"{f.period_start}~{f.period_end}", f.measured_at,
                        f.source, f.confidence, f.verification_status, "", "", ";".join(used.get(f.id, [])),
                        f.label or ""])
        for d in reg.derived.values():
            w.writerow([d.id, "derived", d.brand_id, d.entity or "", d.metric, _val(d.value), d.unit,
                        json.dumps(d.parameters, ensure_ascii=False), "", d.measured_at or "", "", d.confidence, "",
                        f"{d.formula_id}@{d.formula_version}", ";".join(d.derived_from), ";".join(used.get(d.id, [])),
                        d.definition or ""])


def write_outputs(result: BuildResult, qc: QCReport, out_dir: Path, *, imports: list[ImportResult] = (),
                  resolve: Optional[AssetResolver] = None, render_pptx: bool = True, versions: Optional[dict] = None,
                  usage: Optional[dict] = None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if render_pptx:
        paths["pptx"] = render_deck(result.deck, out_dir / "report.pptx", resolve)
    paths["factbook"] = out_dir / "factbook.csv"
    write_factbook(result, paths["factbook"])

    paths["sources"] = out_dir / "sources.csv"
    with paths["sources"].open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["source_id", "title", "url", "upload_key", "publisher", "published_at", "fetched_at", "source_type",
                    "used_in"])
        used_src = {sid: [s.slide_id for s in result.deck.slides if sid in s.source_ids] for sid in result.sources}
        for s in result.sources.values():
            w.writerow([s.id, s.title, s.url or "", s.upload_key or "", s.publisher or "", s.published_at or "",
                        s.fetched_at or "", s.source_type, ";".join(used_src.get(s.id, []))])
        data_sources = sorted({f.source for f in result.metrics.registry.facts.values() if f.usable})
        for name in data_sources:
            w.writerow([f"data:{name}", name, "", "", "", "", "", "csv", "quantitative"])

    paths["assets"] = out_dir / "assets.csv"
    with paths["assets"].open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["asset_id", "version", "source_id", "sha256", "width", "height", "crop_x", "crop_y", "crop_w",
                    "crop_h", "title", "usage_basis", "review_status", "used_in"])
        for a in result.assets.values():
            used = [s.slide_id for s in result.deck.slides if a.id in s.asset_ids]
            w.writerow([a.id, a.version, a.source_id or "", a.sha256, a.width, a.height, a.crop.x, a.crop.y, a.crop.w,
                        a.crop.h, a.title, a.usage_basis, a.review_status, ";".join(used)])

    paths["findings"] = out_dir / "findings.json"
    paths["findings"].write_text(json.dumps([
        {**f.model_dump(mode="json", exclude={"strength", "summary"}), "strength": ser_strength(f.strength),
         "summary": {k: ser(v) if isinstance(v, Decimal) else v for k, v in f.summary.items()}}
        for f in result.findings], ensure_ascii=False, indent=2), encoding="utf-8")
    paths["deck_spec"] = out_dir / "deck_spec.json"
    paths["deck_spec"].write_text(result.deck.model_dump_json(indent=2), encoding="utf-8")

    rejected = [e.model_dump() for imp in imports for e in imp.errors]
    paths["errors"] = out_dir / "errors.csv"
    with paths["errors"].open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "row_no", "column", "code", "message"])
        for e in rejected:
            w.writerow([e["file"], e["row_no"], e["column"] or "", e["code"], e["message"]])

    omitted = [s.model_dump() for s in result.deck.plan if s.readiness == "omitted"]
    missing = [s.model_dump() for s in result.deck.plan if s.readiness == "needs_input"]
    ok = qc.blocks == 0
    status = "blocked" if not ok else ("completed_with_warnings" if (rejected or qc.warns) else "completed")
    report = {
        "ok": ok, "status": status, "qc": qc.to_dict(), "omitted": omitted, "missing": missing,
        "rejected_rows": rejected, "counts": result.deck.counts(),
        "metric_issues": [i.__dict__ for i in result.metrics.issues],
        "usage": usage or {"api_calls": 0}, "versions": {"deck_version": result.deck.deck_version,
                                                        "template_version": result.deck.template_version,
                                                        "input_fingerprint": result.deck.input_fingerprint,
                                                        **(versions or {})},
    }
    paths["build_report"] = out_dir / "build_report.json"
    paths["build_report"].write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return paths
