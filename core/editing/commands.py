"""Typed edit commands on SlideSpecs (editor + AI assistant share one executor).

Commands keep element ids and only touch the fields they name; a slide is never regenerated.
A command that would break the evidence rules (a number typed as plain text, a fact the deck
does not show) is rejected with a reason instead of applied.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter

from core.composition.tokens import tokens
from core.editing.text import DeckVocabulary, TextEditError, from_tokens
from core.schemas.slidespec import (
    Binding, Block, ImageBlock, Paragraph, Part, Region, ShapeBlock, SlideSpec, TableBlock, TextBlock,
)

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
Weight = Literal["light", "regular", "semibold", "bold", "heavy"]
MAX_PT = 96.0


class _Cmd(BaseModel):
    slide_id: str
    reason: str = ""


class UpdateText(_Cmd):
    op: Literal["update_text"] = "update_text"
    element_id: str
    paragraphs: list[str]


class UpdateStyle(_Cmd):
    op: Literal["update_style"] = "update_style"
    element_id: str
    size: Optional[float] = None
    color: Optional[str] = None
    weight: Optional[Weight] = None
    align: Optional[Literal["l", "c", "r"]] = None
    valign: Optional[Literal["t", "m", "b"]] = None
    fill: Optional[str] = None
    line: Optional[str] = None
    line_spacing: Optional[float] = None


class MoveElement(_Cmd):
    op: Literal["move_element"] = "move_element"
    element_id: str
    x: float
    y: float


class ResizeElement(_Cmd):
    op: Literal["resize_element"] = "resize_element"
    element_id: str
    w: float
    h: float
    x: Optional[float] = None
    y: Optional[float] = None


class NewElement(BaseModel):
    kind: Literal["text", "shape", "image"]
    x: float
    y: float
    w: float
    h: float
    paragraphs: list[str] = Field(default_factory=list)  # text: token strings
    size: float = 14.0
    color: str = "text"
    weight: Weight = "regular"
    align: Literal["l", "c", "r"] = "l"
    fill: Optional[str] = None
    line: Optional[str] = None
    shape: Literal["rect", "rounded", "line"] = "rect"
    asset_id: Optional[str] = None


class AddElement(_Cmd):
    op: Literal["add_element"] = "add_element"
    element: NewElement
    element_id: Optional[str] = None  # assigned when omitted


class DeleteElement(_Cmd):
    op: Literal["delete_element"] = "delete_element"
    element_id: str


class ReorderElement(_Cmd):
    op: Literal["reorder_elements"] = "reorder_elements"
    element_id: str
    to: Literal["front", "back", "forward", "backward"]


class UpdateBackground(_Cmd):
    op: Literal["update_background"] = "update_background"
    color: Optional[str]  # None = remove the background fill


class UpdateNotes(_Cmd):
    """Speaker notes are the presenter's script: not on the slide, so digits are allowed."""
    op: Literal["update_notes"] = "update_notes"
    text: str = Field(max_length=6000)


class RenameSlide(_Cmd):
    op: Literal["rename_slide"] = "rename_slide"
    title: str = Field(min_length=1, max_length=120)


class LayoutItem(BaseModel):
    element_id: str
    x: float
    y: float
    w: Optional[float] = None
    h: Optional[float] = None


class RestructureLayout(_Cmd):
    op: Literal["restructure_layout"] = "restructure_layout"
    items: list[LayoutItem]


Command = Annotated[
    Union[UpdateText, UpdateStyle, MoveElement, ResizeElement, AddElement, DeleteElement, ReorderElement,
          UpdateBackground, RestructureLayout, UpdateNotes, RenameSlide],
    Field(discriminator="op"),
]
COMMANDS = TypeAdapter(list[Command])
OPS = ["update_text", "update_style", "move_element", "resize_element", "add_element", "delete_element",
       "reorder_elements", "update_background", "restructure_layout", "update_notes", "rename_slide"]


class CommandError(ValueError):
    pass


@dataclass
class ApplyResult:
    slides: list[SlideSpec]
    applied: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    changed: dict[str, list[str]] = field(default_factory=dict)  # slide_id -> element ids

    def to_dict(self) -> dict:
        return {"slides": [s.model_dump(mode="json") for s in self.slides], "applied": self.applied,
                "rejected": self.rejected, "changed": self.changed}


def _canvas() -> tuple[float, float]:
    c = tokens()["canvas"]
    return float(c["w"]), float(c["h"])


def check_color(value: str) -> str:
    if HEX.match(value):
        return value.upper()
    if value in tokens()["colors"]:
        return value
    raise CommandError(f"알 수 없는 색 '{value}' — #RRGGBB 또는 디자인 토큰 이름을 쓰세요")


def _clamp_region(x: float, y: float, w: float, h: float) -> Region:
    cw, ch = _canvas()
    w = min(max(w, 4.0), cw)
    h = min(max(h, 1.0), ch)
    x = min(max(x, 0.0), cw - w)
    y = min(max(y, 0.0), ch - h)
    return Region(x=round(x, 1), y=round(y, 1), w=round(w, 1), h=round(h, 1))


def _find(slide: SlideSpec, element_id: str) -> tuple[int, Block]:
    for i, b in enumerate(slide.blocks):
        if b.block_id == element_id:
            return i, b
    raise CommandError(f"{slide.slide_id}에 요소 {element_id}가 없습니다")


def _new_id(slide: SlideSpec, prefix: str) -> str:
    used = {b.block_id for b in slide.blocks}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _scale_text(b: TextBlock, size: float):
    ratio = size / b.size if b.size else 1.0
    b.size = round(size, 1)
    b.line_spacing = round(b.line_spacing * ratio, 1)
    for para in b.paragraphs:
        for p in para.parts:
            if p.size:
                p.size = round(p.size * ratio, 1)


def _min_pt() -> float:
    return float(tokens().get("min_font_pt", 6.5))


def _apply_one(slide: SlideSpec, cmd, vocab: DeckVocabulary, allow_digits: bool) -> tuple[str, list[str]]:
    """Mutates `slide`; returns (summary, changed element ids)."""
    if isinstance(cmd, UpdateText):
        _, b = _find(slide, cmd.element_id)
        if not isinstance(b, TextBlock):
            raise CommandError(f"{cmd.element_id}는 텍스트 요소가 아닙니다")
        try:
            paras = from_tokens(cmd.paragraphs, b, vocab, allow_digits=allow_digits)
        except TextEditError as exc:
            raise CommandError(str(exc))
        before = len(b.paragraphs)
        b.paragraphs = paras
        return f"텍스트 변경 ({before}→{len(paras)}문단)", [b.block_id]

    if isinstance(cmd, UpdateStyle):
        _, b = _find(slide, cmd.element_id)
        notes = []
        if cmd.size is not None:
            size = min(max(cmd.size, _min_pt()), MAX_PT)
            if isinstance(b, TextBlock):
                notes.append(f"글자 {b.size:g}→{size:g}pt")
                _scale_text(b, size)
            elif isinstance(b, TableBlock):
                notes.append(f"표 글자 {b.size:g}→{size:g}pt")
                b.header_size = round(b.header_size * size / b.size, 1)
                b.size = round(size, 1)
            else:
                raise CommandError(f"{cmd.element_id}에는 글자 크기가 없습니다")
        if cmd.line_spacing is not None and isinstance(b, TextBlock):
            b.line_spacing = round(max(cmd.line_spacing, b.size), 1)
            notes.append(f"줄 간격 {b.line_spacing:g}pt")
        if cmd.color is not None:
            c = check_color(cmd.color)
            if isinstance(b, TextBlock):
                b.color = c
                for para in b.paragraphs:  # an explicit block color wins over inherited part colors
                    para.color = None
                    for p in para.parts:
                        if p.type != "link":
                            p.color = None
                notes.append(f"글자색 {c}")
            elif isinstance(b, ShapeBlock):
                b.fill = c
                notes.append(f"채우기 {c}")
            else:
                raise CommandError(f"{cmd.element_id}에는 글자색을 바꿀 수 없습니다")
        if cmd.weight is not None:
            if not isinstance(b, TextBlock):
                raise CommandError(f"{cmd.element_id}는 텍스트 요소가 아닙니다")
            b.weight, b.bold = cmd.weight, False
            for para in b.paragraphs:
                para.weight, para.bold = None, False
                for p in para.parts:
                    if p.type != "fact":  # fact chips stay emphasized
                        p.weight, p.bold = None, False
            notes.append(f"굵기 {cmd.weight}")
        if cmd.align is not None and isinstance(b, TextBlock):
            b.align = cmd.align
            notes.append(f"정렬 {cmd.align}")
        if cmd.valign is not None and isinstance(b, TextBlock):
            b.valign = cmd.valign
        if cmd.fill is not None:
            if not isinstance(b, (TextBlock, ShapeBlock)):
                raise CommandError(f"{cmd.element_id}에는 채우기를 쓸 수 없습니다")
            b.fill = None if cmd.fill == "none" else check_color(cmd.fill)
            notes.append(f"채우기 {cmd.fill}")
        if cmd.line is not None:
            if not isinstance(b, ShapeBlock):
                raise CommandError(f"{cmd.element_id}는 도형이 아닙니다")
            b.line = None if cmd.line == "none" else check_color(cmd.line)
            notes.append(f"테두리 {cmd.line}")
        if not notes:
            raise CommandError("바꿀 스타일이 없습니다")
        return ", ".join(notes), [b.block_id]

    if isinstance(cmd, MoveElement):
        _, b = _find(slide, cmd.element_id)
        r = b.region
        b.region = _clamp_region(cmd.x, cmd.y, r.w, r.h)
        return f"이동 ({r.x:g},{r.y:g})→({b.region.x:g},{b.region.y:g})", [b.block_id]

    if isinstance(cmd, ResizeElement):
        _, b = _find(slide, cmd.element_id)
        r = b.region
        b.region = _clamp_region(r.x if cmd.x is None else cmd.x, r.y if cmd.y is None else cmd.y, cmd.w, cmd.h)
        return f"크기 {r.w:g}×{r.h:g}→{b.region.w:g}×{b.region.h:g}", [b.block_id]

    if isinstance(cmd, AddElement):
        e = cmd.element
        reg = _clamp_region(e.x, e.y, e.w, e.h)
        eid = cmd.element_id if cmd.element_id and all(b.block_id != cmd.element_id for b in slide.blocks) else None
        if e.kind == "text":
            eid = eid or _new_id(slide, "text_")
            stub = TextBlock(block_id=eid, role="body", region=reg, paragraphs=[Paragraph()], size=e.size,
                             line_spacing=round(e.size * 1.45, 1), color=check_color(e.color), weight=e.weight,
                             align=e.align, fill=check_color(e.fill) if e.fill else None, editable=True)
            try:
                stub.paragraphs = from_tokens(e.paragraphs or [""], stub, vocab, allow_digits=allow_digits)
            except TextEditError as exc:
                raise CommandError(str(exc))
            slide.blocks.append(stub)
        elif e.kind == "shape":
            eid = eid or _new_id(slide, "shape_")
            slide.blocks.append(ShapeBlock(block_id=eid, region=reg, shape=e.shape,
                                           fill=check_color(e.fill) if e.fill else ("tint" if e.shape != "line" else None),
                                           line=check_color(e.line) if e.line else ("navy" if e.shape == "line" else None)))
        else:
            if not e.asset_id:
                raise CommandError("이미지 요소에는 asset_id가 필요합니다")
            eid = eid or _new_id(slide, "image_")
            slide.blocks.append(ImageBlock(block_id=eid, region=reg, asset_id=e.asset_id))
            if e.asset_id not in slide.asset_ids:
                slide.asset_ids.append(e.asset_id)
        return {"text": "텍스트", "shape": "도형", "image": "이미지"}[e.kind] + " 추가", [eid]

    if isinstance(cmd, DeleteElement):
        i, b = _find(slide, cmd.element_id)
        slide.blocks.pop(i)
        return "요소 삭제", []

    if isinstance(cmd, ReorderElement):
        i, b = _find(slide, cmd.element_id)
        slide.blocks.pop(i)
        floor = 1 if slide.blocks and slide.blocks[0].block_id == "bg" else 0  # the background stays at the back
        j = {"front": len(slide.blocks), "back": floor, "forward": min(i + 1, len(slide.blocks)),
             "backward": max(i - 1, floor)}[cmd.to]
        slide.blocks.insert(j, b)
        return {"front": "맨 앞으로", "back": "맨 뒤로", "forward": "앞으로", "backward": "뒤로"}[cmd.to], [b.block_id]

    if isinstance(cmd, UpdateBackground):
        bg = next((b for b in slide.blocks if isinstance(b, ShapeBlock) and b.block_id == "bg"), None)
        if cmd.color is None:
            if bg:
                slide.blocks.remove(bg)
            return "배경 제거", []
        c = check_color(cmd.color)
        cw, ch = _canvas()
        if bg:
            bg.fill = c
        else:
            slide.blocks.insert(0, ShapeBlock(block_id="bg", region=Region(x=0, y=0, w=cw, h=ch), fill=c))
        return f"배경 {c}", ["bg"]

    if isinstance(cmd, RestructureLayout):
        ids = []
        for it in cmd.items:
            _, b = _find(slide, it.element_id)
            r = b.region
            b.region = _clamp_region(it.x, it.y, r.w if it.w is None else it.w, r.h if it.h is None else it.h)
            ids.append(b.block_id)
        return f"레이아웃 재구성 ({len(ids)}개 요소)", ids

    if isinstance(cmd, UpdateNotes):
        before = len(slide.speaker_notes)
        slide.speaker_notes = cmd.text.strip()
        return f"발표자 메모 {'작성' if not before else '수정'} ({len(slide.speaker_notes)}자)", []

    if isinstance(cmd, RenameSlide):
        old = slide.title
        slide.title = cmd.title.strip()
        return f"슬라이드 이름 '{old}' → '{slide.title}'", []

    raise CommandError(f"지원하지 않는 명령 {getattr(cmd, 'op', cmd)}")


def refresh_bindings(slide: SlideSpec) -> None:
    """Keep bindings in step with where fact chips now are (edits move or drop chips)."""
    where: dict[str, str] = {}
    for b in slide.blocks:
        if isinstance(b, TextBlock):
            for para in b.paragraphs:
                for p in para.parts:
                    if p.type == "fact" and p.fact_id:
                        where.setdefault(p.fact_id, b.block_id)
        elif isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for p in para.parts:
                            if p.type == "fact" and p.fact_id:
                                where.setdefault(p.fact_id, b.block_id)
        else:
            for it in getattr(b, "items", []) or []:
                where.setdefault(it.fact_id, b.block_id)
            for s in getattr(b, "series", []) or []:
                for pt in s.points:
                    if pt.fact_id:
                        where.setdefault(pt.fact_id, b.block_id)
    keep: list[Binding] = []
    for bd in slide.bindings:
        if bd.fact_id not in where:
            continue
        block_ids = {b.block_id for b in slide.blocks}
        if bd.block_id.split("[")[0] not in block_ids:
            bd = bd.model_copy(update={"block_id": where[bd.fact_id]})
        keep.append(bd)
    slide.bindings = keep


def apply_commands(slides: list[SlideSpec], commands: list, *, allow_digits: bool = False,
                   vocab: Optional[DeckVocabulary] = None) -> ApplyResult:
    """Apply in order on copies; each command either applies fully or is rejected."""
    out = [s.model_copy(deep=True) for s in slides]
    by_id = {s.slide_id: s for s in out}
    vocab = vocab or DeckVocabulary(slides)
    result = ApplyResult(slides=out)
    for i, raw in enumerate(commands):
        try:
            cmd = raw if isinstance(raw, BaseModel) else TypeAdapter(Command).validate_python(raw)
        except Exception as exc:  # malformed command from the model
            result.rejected.append({"index": i, "op": (raw or {}).get("op") if isinstance(raw, dict) else None,
                                    "reason": f"명령 형식 오류: {str(exc)[:160]}"})
            continue
        slide = by_id.get(cmd.slide_id)
        if slide is None:
            result.rejected.append({"index": i, "op": cmd.op, "slide_id": cmd.slide_id, "reason": "없는 슬라이드"})
            continue
        trial = slide.model_copy(deep=True)
        try:
            summary, ids = _apply_one(trial, cmd, vocab, allow_digits)
        except CommandError as exc:
            result.rejected.append({"index": i, "op": cmd.op, "slide_id": cmd.slide_id,
                                    "element_id": getattr(cmd, "element_id", None), "reason": str(exc)})
            continue
        refresh_bindings(trial)
        idx = out.index(slide)
        out[idx] = by_id[cmd.slide_id] = trial
        result.applied.append({"index": i, "op": cmd.op, "slide_id": cmd.slide_id,
                               "element_id": getattr(cmd, "element_id", None) or (ids[0] if ids else None),
                               "summary": summary, "reason": cmd.reason})
        bucket = result.changed.setdefault(cmd.slide_id, [])
        bucket += [x for x in ids if x not in bucket]
    return result
