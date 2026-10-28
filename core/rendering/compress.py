"""경량 PPTX 옵션 (09_고객피드백_요구사항화.md: '모바일 원격 확인용 PDF·PPTX — 30MB 이하 경량 PPTX
옵션(이미지 JPEG 압축)'). Every embedded image becomes a resized JPEG — even one that started as a
PNG — because every image this product embeds is a case-card photo shown "contain"-fit; none is
a logo or graphic that needs transparency preserved, so there is no quality reason to keep PNG.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

MAX_DIM = 1600  # px, long edge — comfortably above any on-slide image region at full-deck zoom
QUALITY = 65


def compress_image(src_path: Path, dest_path: Path, *, max_dim: int = MAX_DIM, quality: int = QUALITY) -> tuple[int, int]:
    """Resize + re-encode src as a JPEG at dest; returns the written (width, height)."""
    img = Image.open(src_path)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.LANCZOS)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path, "JPEG", quality=quality, optimize=True)
    return img.size
