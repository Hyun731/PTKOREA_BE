"""What an AI edit request may touch, and the slide context a model sees.

Scope rules (the editor shows the scope before sending):
  selection: only the selected elements, the elements under the marked regions, and new
             elements placed inside a marked region, on the slides those belong to.
  slide:     every element of the current slide.
  deck:      every slide.
Region coordinates arrive relative to the slide (0..1) and are converted to canvas units here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel

from core.composition.tokens import tokens
from core.editing.text import readable, to_tokens
from core.schemas.slidespec import (
    BarChartBlock, ImageBlock, LineChartBlock, Region, ShapeBlock, SlideSpec, TableBlock, TextBlock,
)

Scope = Literal["selection", "slide", "deck"]


class AreaIn(BaseModel):
    """A marked area, relative to the slide (0..1) so zoom never moves it."""
    id: str
    slide_id: str
    x: float
    y: float
    w: float
    h: float


class SelectionIn(BaseModel):
    element_ids: dict[str, list[str]] = {}  # slide_id -> element ids
    areas: list[AreaIn] = []


@dataclass
class Target:
    slide_ids: list[str]
    element_ids: dict[str, set[str]] = field(default_factory=dict)  # empty set = whole slide
    areas: dict[str, list[Region]] = field(default_factory=dict)  # canvas units

    def allows(self, slide_id: str, element_id: Optional[str], new_region: Optional[Region] = None) -> bool:
        if slide_id not in self.slide_ids:
            return False
        ids = self.element_ids.get(slide_id)
        if not ids:  # whole slide
            return True
        if element_id in ids:
            return True
        if new_region is not None:
            cx, cy = new_region.x + new_region.w / 2, new_region.y + new_region.h / 2
            return any(a.x <= cx <= a.x + a.w and a.y <= cy <= a.y + a.h for a in self.areas.get(slide_id, []))
        return False


def to_canvas(a: AreaIn) -> Region:
    c = tokens()["canvas"]
    return Region(x=round(a.x * c["w"], 1), y=round(a.y * c["h"], 1), w=round(a.w * c["w"], 1), h=round(a.h * c["h"], 1))


def overlap_ratio(r: Region, a: Region) -> float:
    """Share of element r that lies inside area a."""
    ix = max(0.0, min(r.x + r.w, a.x + a.w) - max(r.x, a.x))
    iy = max(0.0, min(r.y + r.h, a.y + a.h) - max(r.y, a.y))
    area = max(r.w * r.h, 1.0)
    return ix * iy / area


def elements_in(slide: SlideSpec, area: Region, threshold: float = 0.35) -> list[str]:
    return [b.block_id for b in slide.blocks if b.block_id != "bg" and overlap_ratio(b.region, area) >= threshold]


def resolve_target(slides: list[SlideSpec], current_slide_id: str, scope: Scope, selection: SelectionIn) -> Target:
    ids = [s.slide_id for s in slides]
    if scope == "deck":
        return Target(slide_ids=ids)
    if scope == "slide":
        return Target(slide_ids=[current_slide_id])
    by_id = {s.slide_id: s for s in slides}
    t = Target(slide_ids=[])
    for sid, els in selection.element_ids.items():
        if sid in by_id and els:
            t.element_ids.setdefault(sid, set()).update(els)
    for a in selection.areas:
        if a.slide_id not in by_id:
            continue
        reg = to_canvas(a)
        t.areas.setdefault(a.slide_id, []).append(reg)
        t.element_ids.setdefault(a.slide_id, set()).update(elements_in(by_id[a.slide_id], reg))
    for sid in list(t.element_ids) + list(t.areas):
        if sid not in t.slide_ids:
            t.slide_ids.append(sid)
    for sid in t.slide_ids:  # an empty area still limits the slide to "add inside the area"
        if not t.element_ids.get(sid):
            t.element_ids[sid] = {"__area_only__"}
    if not t.slide_ids:
        return Target(slide_ids=[current_slide_id])
    return t


def element_info(b) -> dict:
    r = b.region
    base = {"id": b.block_id, "kind": b.kind, "x": r.x, "y": r.y, "w": r.w, "h": r.h}
    if isinstance(b, TextBlock):
        base.update({"role": b.role, "size": b.size, "color": b.color, "weight": b.weight or ("bold" if b.bold else "regular"),
                     "align": b.align, "fill": b.fill, "paragraphs": to_tokens(b), "shows": readable(b)})
    elif isinstance(b, ShapeBlock):
        base.update({"shape": b.shape, "fill": b.fill, "line": b.line})
    elif isinstance(b, TableBlock):
        base.update({"columns": [c.label for c in b.columns], "rows": len(b.rows), "size": b.size,
                     "first_rows": [" | ".join("".join(p.rendered() for para in c.paragraphs for p in para.parts) for c in row.cells)
                                    for row in b.rows[:4]]})
    elif isinstance(b, BarChartBlock):
        base.update({"bars": [f"{it.label} {it.display}" for it in b.items]})
    elif isinstance(b, LineChartBlock):
        base.update({"series": [s.entity for s in b.series], "categories": b.categories})
    elif isinstance(b, ImageBlock):
        base.update({"asset_id": b.asset_id})
    return base


def slide_context(slide: SlideSpec, target: Target) -> dict:
    ids = target.element_ids.get(slide.slide_id)
    bg = next((b.fill for b in slide.blocks if isinstance(b, ShapeBlock) and b.block_id == "bg"), None)
    return {
        "slide_id": slide.slide_id, "title": slide.title, "page_role": slide.page_role, "background": bg,
        "speaker_notes": slide.speaker_notes,
        "editable_element_ids": sorted(i for i in ids if i != "__area_only__") if ids else "all",
        "areas": [r.model_dump() for r in target.areas.get(slide.slide_id, [])],
        "elements": [element_info(b) for b in slide.blocks if b.block_id != "bg"],
    }
