"""SlideSpec contract (PRD 8 SlideSpec, 11, 12; DEVELOPMENT_PLAN 4 SlideSpec).

Numbers never live in plain text: they are `fact` parts the server formats. Dates,
target labels, config thresholds and fixed names are typed parts, so QC can tell them
apart from untraced numbers without a global regex exception.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

PartType = Literal["text", "fact", "meta", "date", "name", "link", "quote"]  # quote = verbatim source excerpt
Weight = Literal["light", "regular", "semibold", "bold", "heavy"]  # font weight steps (style tokens)


class Part(BaseModel):
    type: PartType = "text"
    text: Optional[str] = None
    fact_id: Optional[str] = None
    formatter: Optional[str] = None
    display: Optional[str] = None  # server-filled for fact parts
    key: Optional[str] = None  # meta key: period, target_label, config, page, quarter ...
    href: Optional[str] = None
    bold: bool = False
    color: Optional[str] = None  # style token role
    size: Optional[float] = None  # pt override within the block's allowed steps
    weight: Optional[Weight] = None  # overrides bold when set

    def rendered(self) -> str:
        if self.type == "fact":
            return self.display or ""
        return self.text or ""


class Paragraph(BaseModel):
    parts: list[Part] = Field(default_factory=list)
    bullet: Optional[str] = None  # ▸ ┃ → ▲ - etc. rendered as a literal prefix
    color: Optional[str] = None
    bold: bool = False
    weight: Optional[Weight] = None
    space_before: float = 0.0  # pt

    def plain(self) -> str:
        return (self.bullet + " " if self.bullet else "") + "".join(p.rendered() for p in self.parts)


class Region(BaseModel):
    x: float
    y: float
    w: float
    h: float


TextRole = Literal[
    "title", "lead", "caption", "takeaway", "footnote", "panel_header", "body",
    "cover_title", "cover_meta", "index_label", "index_body", "divider_title", "divider_sub", "end", "badge",
    "chip", "meta", "page_no", "insight", "cover_kicker", "cover_sub", "divider_desc", "index_group", "index_item",
]


class TextBlock(BaseModel):
    kind: Literal["text"] = "text"
    block_id: str
    role: TextRole
    region: Region
    paragraphs: list[Paragraph]
    align: Literal["l", "c", "r"] = "l"
    valign: Literal["t", "m", "b"] = "t"
    size: float  # pt
    line_spacing: float  # pt
    color: str = "text"
    bold: bool = False
    weight: Optional[Weight] = None  # block default; bold=True on a part/paragraph still means "bold"
    fill: Optional[str] = None
    max_lines: Optional[int] = None
    editable: bool = False  # set_text allowed through edit commands


class BarItem(BaseModel):
    entity: str
    label: str
    fact_id: str
    display: str
    value: float  # chart data value (display precision)
    role: Literal["self", "key", "other"] = "other"


class BarChartBlock(BaseModel):
    kind: Literal["bar_chart"] = "bar_chart"
    block_id: str
    region: Region
    items: list[BarItem]
    number_format: str = '0.0"%"'
    unit: str = "percent"
    label_size: float = 10.0
    gap_width: int = 55


class LinePoint(BaseModel):
    month: str
    fact_id: Optional[str] = None
    value: Optional[float] = None  # None = missing month, drawn as a gap


class LineSeries(BaseModel):
    entity: str
    role: Literal["self", "key", "other", "other2"] = "other"
    points: list[LinePoint]


class LineChartBlock(BaseModel):
    kind: Literal["line_chart"] = "line_chart"
    block_id: str
    region: Region
    categories: list[str]
    series: list[LineSeries]


class TableCell(BaseModel):
    paragraphs: list[Paragraph] = Field(default_factory=list)
    fill: Optional[str] = None
    bold: bool = False
    color: Optional[str] = None
    align: Optional[Literal["l", "c", "r"]] = None
    merge_down: int = 0  # number of extra rows this cell spans
    merged: bool = False  # covered by a merge from above


class TableColumn(BaseModel):
    key: str
    label: str
    width: float  # fraction of table width
    align: Literal["l", "c", "r"] = "c"


class TableRow(BaseModel):
    cells: list[TableCell]
    muted: bool = False
    ref: Optional[str] = None  # e.g. post_id / source_id for traceability


class TableBlock(BaseModel):
    kind: Literal["table"] = "table"
    block_id: str
    region: Region
    columns: list[TableColumn]
    rows: list[TableRow]
    size: float = 10.0
    header_size: float = 10.0
    header_height: float = 30.0
    row_height: float = 32.0


class Crop(BaseModel):
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0


class ImageBlock(BaseModel):
    kind: Literal["image"] = "image"
    block_id: str
    region: Region
    asset_id: str
    crop: Crop = Field(default_factory=Crop)


class ShapeBlock(BaseModel):
    """Decorative or structural shapes: panel frames, rules, bands."""
    kind: Literal["shape"] = "shape"
    block_id: str
    region: Region
    shape: Literal["rect", "rounded", "line"] = "rect"
    fill: Optional[str] = None
    line: Optional[str] = None
    line_width: float = 0.75


Block = Annotated[
    Union[TextBlock, BarChartBlock, LineChartBlock, TableBlock, ImageBlock, ShapeBlock],
    Field(discriminator="kind"),
]


class Binding(BaseModel):
    block_id: str
    fact_id: str
    entity: Optional[str] = None
    metric: str
    unit: str
    formatter: str
    display: str


PageRole = Literal["cover", "index", "divider", "content", "recap", "appendix", "end"]


class SlideSpec(BaseModel):
    slide_id: str
    version: int = 1
    template_id: str
    template_version: str = "1.0"
    page_role: PageRole
    section_id: Optional[str] = None
    brand_id: Optional[str] = None
    title: str
    blocks: list[Block]
    bindings: list[Binding] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    notes: str = ""  # evidence trace (generated): blocks' text and the fact ids behind them
    speaker_notes: str = ""  # presenter script written in the editor (PowerPoint notes, above the trace)
    parent_slide_id: Optional[str] = None
    page_no: Optional[int] = None
    needs_review: bool = False
    is_data: bool = False  # counts toward "본문 데이터 장표" (PRD 12)

    def block(self, block_id: str):
        for b in self.blocks:
            if b.block_id == block_id:
                return b
        raise KeyError(block_id)


class SlotPlan(BaseModel):
    """SlidePlan slot: planned page vs generated page (PRD E06)."""
    slot_id: str
    section_id: str
    template_id: str
    brand_id: Optional[str] = None
    label: str
    readiness: Literal["ready", "needs_input", "omitted"]
    reason: Optional[str] = None
    required: bool = True
    slide_ids: list[str] = Field(default_factory=list)


class DeckSpec(BaseModel):
    deck_id: str
    deck_version: int = 1
    project_name: str
    template_version: str = "1.0"
    synthetic_data: bool = False
    slides: list[SlideSpec]
    plan: list[SlotPlan]
    input_fingerprint: str = ""

    def counts(self) -> dict[str, int]:
        return {
            "planned": len(self.plan),
            "generated": sum(1 for s in self.plan if s.readiness == "ready"),
            "omitted": sum(1 for s in self.plan if s.readiness == "omitted"),
            "needs_input": sum(1 for s in self.plan if s.readiness == "needs_input"),
            "pages": len(self.slides),
        }
