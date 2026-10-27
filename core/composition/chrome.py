"""Part constructors and the common slide chrome (title, lead, takeaway, footnote)."""
from __future__ import annotations

from datetime import date
from typing import Optional, Union

from core.composition.formatters import fmt_date_dot, fmt_period, format_value
from core.composition.tokens import region, tokens, type_spec
from core.metrics.registry import FactRegistry
from core.schemas.facts import DerivedFact, Fact
from core.schemas.slidespec import Paragraph, Part, Region, TextBlock


class PartFactory:
    """Builds typed parts. Fact parts are always formatted from the registry value."""

    def __init__(self, registry: FactRegistry):
        self.registry = registry

    def fact(self, fact: Union[str, Fact, DerivedFact], formatter: str, bold: bool = True,
             color: Optional[str] = None) -> Part:
        fid = fact if isinstance(fact, str) else fact.id
        obj = self.registry.get(fid)
        if obj is None:
            raise KeyError(f"unknown fact {fid}")
        partial = getattr(obj, "partial", False)
        display = format_value(formatter, obj.value, partial)
        return Part(type="fact", fact_id=fid, formatter=formatter, display=display, bold=bold, color=color)


def T(text: str, bold: bool = False, color: Optional[str] = None, size: Optional[float] = None,
      weight: Optional[str] = None) -> Part:
    return Part(type="text", text=text, bold=bold, color=color, size=size, weight=weight)


def M(text: str, key: str, bold: bool = False, color: Optional[str] = None) -> Part:
    """Metadata reference (window label, target label, config value, section number)."""
    return Part(type="meta", text=text, key=key, bold=bold, color=color)


def D(value: Union[str, date], bold: bool = False, color: Optional[str] = None) -> Part:
    text = fmt_date_dot(value) if isinstance(value, date) else value
    return Part(type="date", text=text, bold=bold, color=color)


def PERIOD(start: date, end: date) -> Part:
    return Part(type="date", text=fmt_period(start, end))


def N(text: str, bold: bool = False, color: Optional[str] = None) -> Part:
    """Fixed name that may contain digits (product or channel name)."""
    return Part(type="name", text=text, bold=bold, color=color)


def L(text: str, href: str, bold: bool = False) -> Part:
    return Part(type="link", text=text, href=href, bold=bold, color="link")


def circled(i: int) -> str:
    """Circled numeral (①②③…) for the numbered-insight pattern, 0-indexed."""
    return chr(0x2460 + i) if i < 20 else f"{i + 1}."


def P(*parts: Part, bullet: Optional[str] = None, color: Optional[str] = None, bold: bool = False,
      weight: Optional[str] = None) -> Paragraph:
    return Paragraph(parts=list(parts), bullet=bullet, color=color, bold=bold, weight=weight)


def text_block(block_id: str, role: str, reg: Region, paragraphs: list[Paragraph], *, spec: str,
               align: str = "l", valign: str = "t", color: str = "text", bold: bool = False,
               fill: Optional[str] = None, editable: bool = False, size: Optional[float] = None,
               line: Optional[float] = None, weight: Optional[str] = None) -> TextBlock:
    ts = type_spec(spec)
    size = size or ts["size"]
    return TextBlock(block_id=block_id, role=role, region=reg, paragraphs=paragraphs, align=align, valign=valign,
                     size=size, line_spacing=line or ts.get("line", round(size * 1.35, 1)), color=color, bold=bold,
                     weight=weight or ts.get("weight"), fill=fill, max_lines=ts.get("max_lines"), editable=editable)


def title_block(main: str, sub: Optional[str] = None, sub_parts: Optional[list[Part]] = None) -> TextBlock:
    """v6 breadcrumb next to the section chip: 'Main  ·  sub'. The slide's message lives in the lead."""
    parts = [T(main)]
    if sub or sub_parts:
        parts.append(T("  ·  "))
        if sub:
            parts.append(T(sub))
        for p in sub_parts or []:
            parts.append(p.model_copy(update={"size": None, "bold": False}))
    return text_block("title", "title", region("title"), [P(*parts)], spec="title", valign="m", color="muted")


def lead_block(paragraphs: list[Paragraph]) -> TextBlock:
    """v6 headline: the slide's message, navy, left aligned, at most two lines."""
    return text_block("lead", "lead", region("lead"), paragraphs, spec="lead", align="l", valign="t", color="navy",
                      editable=True)


def takeaway_block(paragraph: Paragraph) -> TextBlock:
    """v6 summary line over the navy rule (numbered insights, when present, sit under it)."""
    paragraph = paragraph.model_copy(update={"bullet": None})  # v6 has no ▶ marker; the rule does that job
    return text_block("takeaway", "takeaway", region("takeaway"), [paragraph], spec="takeaway", valign="b",
                      color="navy", editable=True)


def insight_blocks(items: list[tuple[list[Part], list[Part]]]) -> list[TextBlock]:
    """Up to three numbered insights under the takeaway rule: (title parts, body parts) each."""
    reg = region("insights")
    n = max(1, min(3, len(items)))
    col_w = (reg.w + 10) / 3 - 10
    out: list[TextBlock] = []
    for i, (title, body) in enumerate(items[:3]):
        x = reg.x + i * (col_w + 10)
        out.append(text_block(f"insight{i}_no", "insight", Region(x=x, y=reg.y, w=20, h=24), [P(M(str(i + 1), "insight_no"))],
                              spec="insight_no", color="navy"))
        out.append(text_block(f"insight{i}_title", "insight", Region(x=x + 21, y=reg.y + 1, w=col_w - 21, h=20), [P(*title)],
                              spec="insight_title", editable=True))
        out.append(text_block(f"insight{i}_body", "insight", Region(x=x + 21, y=reg.y + 26, w=col_w - 21, h=reg.h - 26),
                              [P(*body)], spec="insight_body", editable=True))
    return out if n else []


def footnote_block(paragraphs: list[Paragraph]) -> TextBlock:
    return text_block("footnote", "footnote", region("footnote"), paragraphs, spec="footnote", align="l",
                      valign="t", color="muted")


def synthetic_badge() -> TextBlock:
    reg = Region(x=1072, y=24, w=160, h=22)
    return text_block("badge", "badge", reg, [P(T("합성 테스트 자료", bold=True, color="red"))], spec="caption",
                      align="c", valign="m", fill="badge", size=9, line=12)


def chrome_blocks(chip: str, page_no: Optional[int]) -> list:
    """Frame shared by every content page (v6): top band, section chip, footer rule, page number."""
    from core.schemas.slidespec import ShapeBlock
    band, chip_reg, num = region("band"), region("chip"), region("page_no")
    rule_y = tokens()["regions"]["footer_rule_y"]
    out = [ShapeBlock(block_id="chrome_band", region=band, fill="navy"),
           text_block("chrome_chip", "chip", chip_reg, [P(T(chip))], spec="chip", align="c", valign="m", color="white",
                      fill="navy"),
           ShapeBlock(block_id="chrome_rule", region=Region(x=48, y=rule_y, w=1184, h=0), shape="line", line="rule",
                      line_width=0.5)]
    if page_no is not None:
        out.append(text_block("chrome_page", "page_no", num, [P(M(str(page_no), "page"))], spec="page_no", align="r",
                              color="muted"))
    return out


def body_region() -> Region:
    return region("body")


def canvas() -> tuple[int, int]:
    c = tokens()["canvas"]
    return c["w"], c["h"]
