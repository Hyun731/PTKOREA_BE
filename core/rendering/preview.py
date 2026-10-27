"""Actual-PPTX preview (PRD 11/12): render the generated .pptx with headless LibreOffice.

Backends: `docker` (ptk-render image, see infra/render), `local` (soffice + pdftoppm on
PATH) or `none`. A web HTML preview is never presented as proof of PowerPoint output.
LibreOffice is a proxy; the target PowerPoint check stays a manual QUALITY_BASELINE step.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

RENDER_IMAGE = os.environ.get("RENDER_IMAGE", "ptk-render:0.3")


class RenderUnavailable(RuntimeError):
    pass


def backend() -> str:
    configured = os.environ.get("RENDER_BACKEND")
    if configured:
        return configured
    if shutil.which("soffice") and shutil.which("pdftoppm"):
        return "local"
    if shutil.which("docker"):
        return "docker"
    return "none"


def render_pages(pptx: Path, out_dir: Path, dpi: int = 96, timeout: int = 240) -> list[Path]:
    pptx = pptx.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    mode = backend()
    if mode == "docker":
        work = pptx.parent
        rel_out = os.path.relpath(out_dir, work)
        if rel_out.startswith(".."):
            raise RenderUnavailable("preview out_dir must be inside the pptx directory for the docker backend")
        cmd = ["docker", "run", "--rm", "--network", "none", "-v", f"{work}:/work", RENDER_IMAGE,
               f"/work/{pptx.name}", f"/work/{rel_out}", str(dpi)]
    elif mode == "local":
        cmd = ["sh", str(Path(__file__).resolve().parents[2] / "infra" / "render" / "render.sh"), str(pptx), str(out_dir), str(dpi)]
    else:
        raise RenderUnavailable("렌더러가 설정되지 않았습니다 (RENDER_BACKEND=docker|local)")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RenderUnavailable(f"render failed: {proc.stderr.strip()[-400:]}")
    pages = sorted(out_dir.glob("page-*.png"))
    if not pages:
        raise RenderUnavailable("render produced no pages")
    return pages
