"""Stage 0B: build the 8-template verification deck, render it, and place each page next
to its Samsonite reference page at the same size for the QUALITY_BASELINE comparison.

    .venv/bin/python tools/quality_deck.py [--reference /path/to/samsonite.pdf]

Outputs under var/quality/: verification.pptx, preview/, compare_pNN.png, qc.json.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.composition.build import BuildInputs, build_deck  # noqa: E402
from core.composition.tokens import FONTS_DIR  # noqa: E402
from core.quality.qc import run_qc  # noqa: E402
from core.rendering.pptx_renderer import render_deck  # noqa: E402
from core.rendering.preview import RENDER_IMAGE, render_pages  # noqa: E402
from tests.quality_fixture import REFERENCE_PAGES, build_inputs  # noqa: E402
from tools.contact_sheet import sheet  # noqa: E402

DEFAULT_REF = Path.home() / "Downloads/drive-download-20261011T124052Z-1-001/샘소나이트_세션1_마케팅활동점검 1001.pdf"


def reference_pages(pdf: Path, out: Path) -> dict[int, Path]:
    out.mkdir(parents=True, exist_ok=True)
    found = {}
    for page in REFERENCE_PAGES:
        target = out / f"ref-{page:03d}.png"
        if not target.exists():
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "pdftoppm",
                            "-v", f"{pdf.parent}:/ref:ro", "-v", f"{out}:/out", RENDER_IMAGE,
                            "-r", "72", "-f", str(page), "-l", str(page), "-png", "-singlefile",
                            f"/ref/{pdf.name}", f"/out/ref-{page:03d}"], check=True, capture_output=True)
        found[page] = target
    return found


def side_by_side(ref: Path, ours: Path, out: Path, label: str):
    w = 960
    a = Image.open(ref).convert("RGB")
    b = Image.open(ours).convert("RGB")
    h = int(w * 9 / 16)
    a, b = a.resize((w, h), Image.LANCZOS), b.resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w * 2 + 30, h + 50), "#444")
    canvas.paste(a, (10, 40))
    canvas.paste(b, (w + 20, 40))
    font = ImageFont.truetype(str(FONTS_DIR / "NotoSansKR-Bold.otf"), 18)
    d = ImageDraw.Draw(canvas)
    d.text((14, 10), f"Reference {label}", fill="white", font=font)
    d.text((w + 24, 10), "Generated (LibreOffice render of native PPTX)", fill="white", font=font)
    canvas.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default=str(DEFAULT_REF))
    ap.add_argument("--out", default=str(ROOT / "var" / "quality"))
    args = ap.parse_args()
    out = Path(args.out)
    project, facts, posts, materials = build_inputs(out / "assets")
    result = build_deck(BuildInputs(project=project, facts=facts, posts=posts, materials=materials,
                                    omitted_slots={"3-1-B2": "검증 덱 범위 외(게시물 입력 없음)",
                                                   "3-1-B3": "검증 덱 범위 외(게시물 입력 없음)"},
                                    generated_on=date(2026, 10, 12)))
    assets = result.assets
    qc = run_qc(result.deck, result.metrics.registry, lambda aid: assets.get(aid))
    (out / "qc.json").write_text(json.dumps(qc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    pptx = render_deck(result.deck, out / "verification.pptx", lambda aid: (assets[aid].path, assets[aid].width, assets[aid].height))
    pages = render_pages(pptx, out / "preview")
    sheet(pages, out / "sheet.png", 3)
    ids = [s.slide_id for s in result.deck.slides]
    print("slides:", ids)
    print("qc:", qc.blocks, "blocks /", qc.warns, "warns")
    for i in qc.issues:
        if i.severity == "block":
            print("  BLOCK", i.code, i.slide_id, i.block_id, i.message)
    ref = Path(args.reference)
    if ref.exists():
        refs = reference_pages(ref, out / "reference")
        for page, slide_id in REFERENCE_PAGES.items():
            if slide_id in ids:
                side_by_side(refs[page], pages[ids.index(slide_id)], out / f"compare_p{page:03d}.png", f"p.{page}")
        print("comparisons written to", out)
    else:
        print("reference PDF not found; skipped side-by-side")


if __name__ == "__main__":
    main()
