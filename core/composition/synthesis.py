"""Synthesis pages (팩트북 표준 목차 0, 7): Executive Summary, SWOT, and next steps.

They are written from the deck's own pages (app.services.synthesis) and only ever restate what a
body page shows, so they carry no numbers of their own. Each is plain text in the v6 pillar look:
navy headers over light panels, the message in the lead.
"""
from __future__ import annotations

from typing import Optional

from core.composition.chrome import L, M, N, P, T, PartFactory, footnote_block, lead_block, text_block, title_block
from core.composition.formatters import UNIT_FORMATTER
from core.schemas.slidespec import Block, Region, ShapeBlock, SlideSpec

C_LABELS = [("company", "Company · 자사"), ("competitor", "Competitor · 경쟁사"), ("customer", "Customer · 소비자")]
SWOT_LABELS = [("S", "Strength · 강점"), ("W", "Weakness · 약점"), ("O", "Opportunity · 기회"), ("T", "Threat · 위협")]


def _line_text(line) -> str:
    return line.get("text", "") if isinstance(line, dict) else str(line)


def _line_parts(line, pf: Optional[PartFactory]) -> list:
    if not isinstance(line, dict):
        return [T(str(line))]
    parts = [T(line.get("text", ""))]
    fact_ref = line.get("fact_ref")
    if fact_ref and pf and fact_ref in pf.registry:
        fact = pf.registry.get(fact_ref)
        parts += [T(" "), pf.fact(fact_ref, UNIT_FORMATTER.get(fact.unit, "int"), bold=True)]
    ref = line.get("ref")
    if ref:
        parts.append(T(" "))
        parts.append(L(f"[{ref}]", line["source_url"]) if line.get("source_url") else M(f"[{ref}]", "slide_ref"))
    return parts


def _panel(i: int, x: float, y: float, w: float, h_head: float, h_body: float, head: str, lines: list,
           numbered: bool = False, no: str = "", pf: Optional[PartFactory] = None) -> list[Block]:
    head_r, body_r = Region(x=x, y=y, w=w, h=h_head), Region(x=x, y=y + h_head + 8, w=w, h=h_body)
    paras = []
    for k, line in enumerate(lines):
        p = P(*_line_parts(line, pf))
        p.bullet = f"{k + 1}." if numbered else "•"
        p.space_before = 8 if k else 0
        paras.append(p)
    return [ShapeBlock(block_id=f"panel{i}_head_bg", region=head_r, fill="navy"),
            # A panel number is a label (meta part), not a figure that needs a source.
            text_block(f"panel{i}_head", "panel_header", head_r, [P(*([M(no, "item_no"), T(" ")] if no else []), T(head))],
                       spec="pillar_header", align="c",
                       valign="m", color="white", bold=True),
            ShapeBlock(block_id=f"panel{i}_body_bg", region=body_r, fill="pillar_body"),
            text_block(f"panel{i}_body", "body", Region(x=x + 16, y=body_r.y + 12, w=w - 32, h=h_body - 24), paras,
                       spec="pillar_body", valign="t")]


TOP, BOTTOM = 140, 630  # free band between the lead and the footnote


def _body_h(lines: list, w: float, per_line: float = 22) -> float:
    """Panel body height from its text: about 40 Korean characters per 372px line, plus padding."""
    chars = max(1, int(w / 9.5))
    rows = sum(max(1, -(-len(_line_text(t)) // chars)) for t in lines) + max(0, len(lines) - 1) * 0.4
    return max(96, rows * per_line + 28)


def _top(total_h: float) -> float:
    """Panels start right under the lead, like the body pages; only an over-tall set moves up into the band."""
    return max(TOP - 20, min(TOP, BOTTOM - total_h))


def _note() -> Block:
    return footnote_block([P(T("본문 장표의 헤드라인과 근거를 종합한 요약 — 새 수치를 더하지 않음"))])


def es_page(es: dict, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    cols = [(k, label, es.get(k) or []) for k, label in C_LABELS if es.get(k)]
    if not cols:
        return None
    n = len(cols)
    w = {1: 520, 2: 520, 3: 372}[n]
    gap = 32
    x0 = 640 - (n * w + (n - 1) * gap) / 2
    blocks: list[Block] = [title_block("Executive Summary", "핵심 요약")]
    if es.get("task"):
        blocks.append(lead_block([P(T(es["task"]))]))
    insights = (es.get("insights") or [])[:3]
    if insights:
        summary_lines = [{"text": f"{it.get('title', '')} — {it.get('body', '')}", "ref": it.get("ref"),
                          "fact_ref": it.get("fact_ref"), "source_url": it.get("source_url")} for it in insights]
        summary_y, summary_h = 132, max(72, _body_h(summary_lines, 1152, 16))
        blocks += [ShapeBlock(block_id="summary_bg", region=Region(x=48, y=summary_y, w=1184, h=summary_h),
                              fill="pillar_body"),
                   text_block("summary", "insight", Region(x=64, y=summary_y + 10, w=1152, h=summary_h - 20),
                              [P(*_line_parts(line, pf), bullet=f"{i + 1}.") for i, line in enumerate(summary_lines)],
                              spec="insight_body")]
    h = max(_body_h(lines, w - 32) for _, _, lines in cols)
    y = max(225 if insights else TOP, _top(48 + 8 + h))
    for i, (_, label, lines) in enumerate(cols):
        blocks += _panel(i, x0 + i * (w + gap), y, w, 48, h, label, lines, pf=pf)
    blocks.append(_note())
    return SlideSpec(slide_id="ES", template_id="exec_summary.v1", page_role="recap", section_id="recap",
                     title="Executive Summary", blocks=blocks, is_data=False)


def swot_page(swot: dict, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    if not any(swot.get(k) for k, _ in SWOT_LABELS):
        return None
    blocks: list[Block] = [title_block("SWOT", sub_parts=[N("3C"), T(" 종합 진단")])]
    if swot.get("lead"):
        blocks.append(lead_block([P(T(swot["lead"]))]))
    w, gap = 580, 20
    h_body = max(_body_h(swot.get(k) or [], w - 32) for k, _ in SWOT_LABELS)
    y = _top(2 * (32 + 8 + h_body) + gap)
    for i, (k, label) in enumerate(SWOT_LABELS):
        r, c = divmod(i, 2)
        blocks += _panel(i, 48 + c * (w + gap), y + r * (h_body + 40 + gap), w, 32, h_body, label,
                         swot.get(k) or [], pf=pf)
    blocks.append(_note())
    return SlideSpec(slide_id="SWOT", template_id="swot.v1", page_role="recap", section_id="recap", title="SWOT",
                     blocks=blocks, is_data=False)


def _items_page(slide_id: str, template: str, heading: str, sub: str, title: str, data: dict,
                items_key: str, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    """Up to 3 numbered title+body panels — insights(type=insight) and solutions(type=problem) share
    this exact v6 pillar layout, just with different framing text."""
    items = (data.get(items_key) or [])[:3]
    if not items:
        return None
    n = len(items)
    w = {1: 520, 2: 520, 3: 372}[n]
    gap = 32
    x0 = 640 - (n * w + (n - 1) * gap) / 2
    blocks: list[Block] = [title_block(heading, sub)]
    if data.get("lead"):
        blocks.append(lead_block([P(T(data["lead"]))]))
    lines = [{"text": it.get("body", ""), "ref": it.get("ref"), "fact_ref": it.get("fact_ref"),
              "source_url": it.get("source_url")} for it in items]
    h = max(_body_h([line], w - 32) for line in lines)
    y = _top(60 + 8 + h)
    for i, (it, line) in enumerate(zip(items, lines)):
        blocks += _panel(i, x0 + i * (w + gap), y, w, 60, h, it.get("title", ""), [line], no=f"{i + 1}.", pf=pf)
    blocks.append(_note())
    return SlideSpec(slide_id=slide_id, template_id=template, page_role="recap", section_id="recap", title=title,
                     blocks=blocks, is_data=False)


def insight_page(insight: dict, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    return _items_page("INSIGHT", "insight.v1", "Insight", "핵심 인사이트", "핵심 인사이트", insight,
                       "insights", pf)


def solution_page(problem: dict, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    return _items_page("SOLUTION", "solution.v1", "Solution", "솔루션 방향", "솔루션 방향", problem,
                       "solutions", pf)


def problem_page(problem: dict, pf: Optional[PartFactory] = None) -> Optional[SlideSpec]:
    """문제 정의: 본문에서 드러난 문제 2~3개를 한 패널에 번호로."""
    problems = problem.get("problems") or []
    if not problems:
        return None
    blocks: list[Block] = [title_block("Problem", "문제 정의")]
    if problem.get("lead"):
        blocks.append(lead_block([P(T(problem["lead"]))]))
    w = 1184
    h = _body_h(problems, w - 32)
    y = _top(48 + 8 + h)
    blocks += _panel(0, 48, y, w, 48, h, "문제", problems, numbered=True, pf=pf)
    blocks.append(_note())
    return SlideSpec(slide_id="PROBLEM", template_id="problem.v1", page_role="recap", section_id="recap",
                     title="문제 정의", blocks=blocks, is_data=False)
