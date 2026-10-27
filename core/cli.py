"""Offline CLI for development and regression (PRD 12: exit 0 ok / 1 input error / 2 QC block).

    python -m core.cli build --project project.json --facts facts.csv --posts posts.csv \
        --out out/ --accept-batches [--preview]

Batches are only used when --accept-batches is passed, mirroring the manual batch
acceptance required in the web flow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from core.composition.build import BuildInputs, build_deck
from core.export import write_outputs
from core.ingestion.acceptance import accept_batch
from core.ingestion.csv_import import import_facts_csv, import_posts_csv
from core.quality.qc import run_qc
from core.schemas.project import load_project


def cmd_build(args) -> int:
    try:
        project = load_project(json.loads(Path(args.project).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"[INVALID_PROJECT] {exc}", file=sys.stderr)
        return 1
    imports = []
    try:
        facts = import_facts_csv(Path(args.facts).read_text(encoding="utf-8"), project, "cli-facts", Path(args.facts).name)
        imports.append(facts)
        posts = None
        if args.posts:
            posts = import_posts_csv(Path(args.posts).read_text(encoding="utf-8"), project, "cli-posts", Path(args.posts).name)
            imports.append(posts)
    except OSError as exc:
        print(f"[INVALID_FILE] {exc}", file=sys.stderr)
        return 1
    if any(e.code == "MISSING_COLUMN" for imp in imports for e in imp.errors):
        print("[INVALID_FILE] 필수 열 누락", file=sys.stderr)
        return 1
    if not facts.facts and not (posts and posts.posts):
        print("[INVALID_ROW] 유효한 입력 행이 없습니다", file=sys.stderr)
        return 1
    if args.accept_batches:
        imports = [accept_batch(i) for i in imports]
    all_facts = [f for i in imports for f in i.facts]
    all_posts = [p for i in imports for p in i.posts]
    result = build_deck(BuildInputs(project=project, facts=all_facts, posts=all_posts,
                                    generated_on=date.fromisoformat(args.date) if args.date else None))
    qc = run_qc(result.deck, result.metrics.registry, lambda aid: result.assets.get(aid))
    out = Path(args.out)
    paths = write_outputs(result, qc, out, imports=imports, render_pptx=qc.blocks == 0 or args.force_pptx)
    if args.preview and "pptx" in paths:
        from core.rendering.preview import render_pages
        render_pages(paths["pptx"], out / "preview")
    report = json.loads(paths["build_report"].read_text(encoding="utf-8"))
    print(json.dumps({"status": report["status"], "counts": report["counts"], "qc_blocks": qc.blocks, "qc_warns": qc.warns},
                     ensure_ascii=False))
    for issue in qc.issues:
        if issue.severity == "block":
            print(f"  BLOCK {issue.code} {issue.slide_id or ''}/{issue.block_id or ''}: {issue.message}", file=sys.stderr)
    return 0 if qc.blocks == 0 else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ptk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--project", required=True)
    b.add_argument("--facts", required=True)
    b.add_argument("--posts")
    b.add_argument("--out", required=True)
    b.add_argument("--accept-batches", action="store_true")
    b.add_argument("--preview", action="store_true")
    b.add_argument("--force-pptx", action="store_true", help="write the pptx even when QC blocks (review only)")
    b.add_argument("--date", help="cover date override YYYY-MM-DD")
    args = ap.parse_args(argv)
    return cmd_build(args)


if __name__ == "__main__":
    sys.exit(main())
