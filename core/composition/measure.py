"""Text measurement with the actual font files (PRD 12: measure wrap/height before render).

Logical units are px at 96 dpi (1 unit = 9525 EMU), so a pt size maps to pt*4/3 px.
Wrapping mirrors PowerPoint's Korean behaviour closely enough for overflow QC: break at
spaces, and break inside a word only when the word alone is wider than the line.
This is a pre-render estimate; the real-render check remains the final gate.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont

from core.composition.tokens import FONTS_DIR, weight_info
from core.schemas.slidespec import Paragraph

PX_PER_PT = 96 / 72


@lru_cache(maxsize=128)
def _font(size_pt: float, weight) -> ImageFont.FreeTypeFont:
    """weight: a weight name from the style tokens, or a legacy bool (True = bold)."""
    name = weight_info(weight)["file"]
    # Measure at 10x for sub-pixel accuracy.
    return ImageFont.truetype(str(FONTS_DIR / name), size=max(1, round(size_pt * PX_PER_PT * 10)))


def text_width(text: str, size_pt: float, bold: bool = False) -> float:
    if not text:
        return 0.0
    return _font(size_pt, bold).getlength(text) / 10


Run = tuple[str, object]  # (text, weight name or legacy bool)


def paragraph_runs(p, block_weight=None, block_bold: bool = False) -> list[Run]:
    """Runs of a Paragraph with each run's resolved weight (same rule the renderer uses)."""
    from core.composition.tokens import resolve_weight
    runs: list[Run] = []
    if p.bullet:
        runs.append((p.bullet + " ", resolve_weight(None, False, p.weight, p.bold, block_weight, block_bold)))
    runs += [(part.rendered(), resolve_weight(part.weight, part.bold, p.weight, p.bold, block_weight, block_bold))
             for part in p.parts]
    return runs


def wrap_runs(runs: list[Run], width: float, size_pt: float) -> list[float]:
    """Return the measured width of each wrapped line for a paragraph made of runs."""
    tokens: list[tuple[str, bool]] = []
    for text, bold in runs:
        buf = ""
        for ch in text:
            if ch == " ":
                if buf:
                    tokens.append((buf, bold))
                    buf = ""
                tokens.append((" ", bold))
            elif ch == "\n":
                if buf:
                    tokens.append((buf, bold))
                    buf = ""
                tokens.append(("\n", bold))
            else:
                buf += ch
        if buf:
            tokens.append((buf, bold))

    lines: list[float] = []
    cur = 0.0
    for tok, bold in tokens:
        if tok == "\n":
            lines.append(cur)
            cur = 0.0
            continue
        w = text_width(tok, size_pt, bold)
        if tok == " ":
            if cur > 0:
                cur += w
            continue
        if cur + w <= width + 0.5:
            cur += w
            continue
        if cur > 0:
            lines.append(cur)
            cur = 0.0
        # A single word wider than the line: break by characters.
        if w > width:
            for ch in tok:
                cw = text_width(ch, size_pt, bold)
                if cur + cw > width + 0.5 and cur > 0:
                    lines.append(cur)
                    cur = 0.0
                cur += cw
        else:
            cur = w
    lines.append(cur)
    return lines


def line_count(runs: list[Run], width: float, size_pt: float) -> int:
    return len(wrap_runs(runs, width, size_pt))


def max_line_width(runs: list[Run], width: float, size_pt: float) -> float:
    return max(wrap_runs(runs, width, size_pt))


def height_at(paragraphs: list[Paragraph], width: float, size_pt: float, line_pt: float) -> float:
    """Paragraph block height at an explicit size/line (vs. a named type_spec)."""
    lines = 0
    extra = 0.0
    for p in paragraphs:
        lines += line_count([(p.plain(), p.bold)], width, size_pt)
        extra += p.space_before
    return (lines * line_pt + extra) * PX_PER_PT
