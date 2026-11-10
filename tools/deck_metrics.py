"""덱 품질 측정 도구 (P1-3): PPTX 하나 이상을 같은 기준으로 재서 나란히 보여준다.

    .venv/bin/python -m tools.deck_metrics 지향.pptx 우리.pptx [--json out.json] [--slides]

재는 것 (IMPROVEMENT_PLAN.md 0장 목표표와 같은 항목)
- 장수, 본문 장수(표지·간지·목차처럼 글이 적은 장 제외)
- 차트(종류별), 표, 그림 — 그룹 안의 도형까지
- 본문 장당 숫자 개수(텍스트·표·차트 값)
- 헤드라인 형식: 위 25% 영역에 '주장 + 수치가 든 근거 줄(-로 시작)'이 있는 본문 장 비율
- 하단 번호 인사이트: 본문 아래쪽에 번호(1·2·3, ①②③) 항목이 2개 이상 있는 본문 장 비율
- 아래가 빈 장: 헤드라인 아래 ~ 각주 위 영역에서 맨 아래 도형 밑이 35% 이상 빈 본문 장

우리 덱은 도형 이름(lead, lead_evidence, insight*, footnote)으로 정확히 재고, 다른 덱(지향 덱 등)은
배치로 추정한다. 그래서 다른 덱 수치는 '대략'이다 — 같은 덱을 다시 재서 진척을 비교하는 용도.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

BODY_MIN_CHARS = 150  # 이보다 글이 적은 장은 표지·간지·목차로 보고 본문에서 뺀다
HEAD_ZONE = 0.25  # 슬라이드 높이의 위 25% = 헤드라인 영역(헤드라인 + 근거 줄)
FOOT_ZONE = 0.88  # 이 아래에서 시작하는 글 = 각주
EMPTY_LIMIT = 0.35
NUMBER = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?")
EVIDENCE_LINE = re.compile(r"^\s*[-–·•▸]\s*\S")
NUMBERED = re.compile(r"^\s*(?:[1-3](?:[.)]|\s|$)|[①②③])")
DIVIDER_NAMES = ("divider_", "cover_", "index_", "end_", "Div")  # Div*: 지향 덱의 간지 도형 이름


@dataclass
class SlideMetrics:
    no: int
    body: bool
    chars: int
    numbers: int
    charts: list[str] = field(default_factory=list)
    tables: int = 0
    pictures: int = 0
    headline_ok: bool = False
    insights_ok: bool = False
    bottom_empty: float = 0.0  # 본문 영역에서 맨 아래 도형 밑으로 빈 비율


@dataclass
class DeckMetrics:
    path: str
    slides: int
    body_slides: int
    charts: int
    chart_kinds: dict[str, int]
    tables: int
    pictures: int
    numbers_per_body: float
    headline_rate: float
    insights_rate: float
    empty_slides: list[int]
    per_slide: list[SlideMetrics] = field(default_factory=list)


def _walk(shapes) -> Iterable:
    for sh in shapes:
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(sh.shapes)
        else:
            yield sh


def _text_of(sh) -> str:
    parts = []
    if sh.has_text_frame:
        parts.append(sh.text_frame.text)
    if getattr(sh, "has_table", False) and sh.has_table:
        parts += [c.text for r in sh.table.rows for c in r.cells]
    return "\n".join(parts)


def _chart_numbers(chart) -> int:
    n = 0
    for plot in chart.plots:
        for s in plot.series:
            n += sum(1 for v in s.values if v is not None)
    return n


def _paragraphs(sh) -> list[str]:
    return [p.text for p in sh.text_frame.paragraphs] if sh.has_text_frame else []


def _headline_ok(shapes: list, height: int) -> bool:
    """주장 + 수치 근거 줄. 우리 덱: lead_evidence 도형에 숫자가 있음. 다른 덱: 헤드라인 영역의 글에서
    첫 문단이 아닌 근거 줄('-'로 시작)에 숫자가 있음."""
    for sh in shapes:
        if sh.name == "lead_evidence" and NUMBER.search(_text_of(sh)):
            return True
    # 근거 줄은 헤드라인과 같은 글상자의 둘째 줄일 수도, 바로 아래 따로 놓인 글상자일 수도 있다.
    head = [sh for sh in shapes if sh.has_text_frame and sh.top is not None and sh.top <= height * HEAD_ZONE
            and sh.text_frame.text.strip()]
    claim = any(not EVIDENCE_LINE.match(_paragraphs(sh)[0] or "") for sh in head)
    evidence = any(EVIDENCE_LINE.match(p) and NUMBER.search(p) for sh in head for p in _paragraphs(sh))
    return claim and evidence


def _insights_ok(shapes: list, body_top: int, body_bottom: int) -> bool:
    """우리 덱: insight0_title처럼 이름 붙은 인사이트가 2개 이상. 다른 덱: 본문 아래쪽 40%에
    번호로 시작하는 글이 2개 이상."""
    named = {sh.name.split("_")[0] for sh in shapes if sh.name.startswith("insight") and _text_of(sh).strip()}
    if len(named) >= 2:
        return True
    lower = body_top + (body_bottom - body_top) * 0.6
    hits = 0
    for sh in shapes:
        if sh.has_text_frame and sh.top is not None and sh.top >= lower:
            hits += sum(1 for p in _paragraphs(sh) if NUMBERED.match(p) and len(p.strip()) > 1)
            hits += 1 if NUMBERED.match(sh.text_frame.text) and len(sh.text_frame.text.strip()) <= 2 else 0
    return hits >= 2


def _bottom_empty(shapes: list, width: int, height: int) -> tuple[float, int, int]:
    """헤드라인 아래 ~ 각주 위를 본문 영역으로 보고, 맨 아래 도형의 바닥부터 본문 끝까지 빈 비율."""
    head_bottom = 0
    foot_top = int(height * 0.92)
    content = []
    for sh in shapes:
        if sh.top is None or sh.height is None or sh.width is None:
            continue
        if sh.width >= width * 0.95 and sh.height >= height * 0.9:  # 배경
            continue
        if sh.height == 0 or sh.width == 0:  # 선
            continue
        if sh.name == "footnote" or (sh.has_text_frame and sh.top >= height * FOOT_ZONE):
            foot_top = min(foot_top, sh.top)
            continue
        if sh.name.startswith("chrome_"):
            continue
        if sh.top + sh.height <= height * HEAD_ZONE or sh.name in ("title", "lead", "lead_claim", "lead_evidence"):
            head_bottom = max(head_bottom, sh.top + sh.height)
            continue
        content.append(sh)
    top, bottom = head_bottom, foot_top
    if bottom - top <= 0:
        return 0.0, top, bottom
    lowest = max((min(sh.top + sh.height, bottom) for sh in content), default=top)
    return max(0.0, (bottom - lowest) / (bottom - top)), top, bottom


def measure(path: Path) -> DeckMetrics:
    prs = Presentation(str(path))
    width, height = prs.slide_width, prs.slide_height
    per: list[SlideMetrics] = []
    for i, slide in enumerate(prs.slides, start=1):
        shapes = list(_walk(slide.shapes))
        text = "\n".join(_text_of(sh) for sh in shapes)
        chars = len(re.sub(r"\s", "", text))
        charts, tables, pictures, numbers = [], 0, 0, len(NUMBER.findall(text))
        for sh in shapes:
            if getattr(sh, "has_chart", False) and sh.has_chart:
                charts.append(str(sh.chart.chart_type).split(".")[-1].split(" ")[0])
                numbers += _chart_numbers(sh.chart)
            if getattr(sh, "has_table", False) and sh.has_table:
                tables += 1
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pictures += 1
        divider = any(sh.name.startswith(DIVIDER_NAMES) for sh in shapes)
        body = chars >= BODY_MIN_CHARS and not divider
        m = SlideMetrics(no=i, body=body, chars=chars, numbers=numbers, charts=charts, tables=tables, pictures=pictures)
        if body:
            m.bottom_empty, top, bottom = _bottom_empty(shapes, width, height)
            m.headline_ok = _headline_ok(shapes, height)
            m.insights_ok = _insights_ok(shapes, top, bottom)
        per.append(m)
    body = [m for m in per if m.body]
    kinds = Counter(k for m in per for k in m.charts)
    rate = lambda pred: round(100 * sum(1 for m in body if pred(m)) / len(body), 1) if body else 0.0  # noqa: E731
    return DeckMetrics(
        path=str(path), slides=len(per), body_slides=len(body), charts=sum(kinds.values()), chart_kinds=dict(kinds),
        tables=sum(m.tables for m in per), pictures=sum(m.pictures for m in per),
        numbers_per_body=round(sum(m.numbers for m in body) / len(body), 1) if body else 0.0,
        headline_rate=rate(lambda m: m.headline_ok), insights_rate=rate(lambda m: m.insights_ok),
        empty_slides=[m.no for m in body if m.bottom_empty >= EMPTY_LIMIT], per_slide=per)


ROWS = [("장수", lambda d: d.slides), ("본문 장수", lambda d: d.body_slides), ("차트", lambda d: d.charts),
        ("차트 종류", lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.chart_kinds.items())) or "-"),
        ("표", lambda d: d.tables), ("그림", lambda d: d.pictures), ("본문 장당 숫자", lambda d: d.numbers_per_body),
        ("주장+근거 헤드라인", lambda d: f"{d.headline_rate}%"), ("하단 번호 인사이트", lambda d: f"{d.insights_rate}%"),
        ("아래 35%+ 빈 장", lambda d: f"{len(d.empty_slides)}장")]


def table(decks: list[DeckMetrics]) -> str:
    head = ["지표", *[Path(d.path).name for d in decks]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for label, get in ROWS:
        lines.append("| " + " | ".join([label, *[str(get(d)) for d in decks]]) + " |")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="PPTX 덱 품질 측정")
    ap.add_argument("decks", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, help="결과를 JSON으로 저장")
    ap.add_argument("--slides", action="store_true", help="본문 장별 세부(빈 비율·헤드라인·인사이트)도 출력")
    args = ap.parse_args(argv)
    decks = [measure(p) for p in args.decks]
    print(table(decks))
    for d in decks:
        if d.empty_slides:
            print(f"\n{Path(d.path).name} 아래가 빈 장: {', '.join(map(str, d.empty_slides))}")
        if args.slides:
            for m in d.per_slide:
                if m.body:
                    print(f"  p{m.no:>3} 빈 {m.bottom_empty:4.0%} 헤드라인 {'O' if m.headline_ok else '-'} "
                          f"인사이트 {'O' if m.insights_ok else '-'} 차트 {len(m.charts)} 표 {m.tables} 숫자 {m.numbers}")
    if args.json:
        args.json.write_text(json.dumps([asdict(d) for d in decks], ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
