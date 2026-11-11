"""리서치 5대 축 장표 (IMPROVEMENT_PLAN P4-4).

| 장 | 무엇 | 자료 |
|---|---|---|
| MK1 | 시장 규모·성장: 큰 숫자(시장 규모·연평균 성장률) + 거시 지표 선 차트 | 시장 수치 Fact(P4-1) |
| DM1 | 품목별 수요·시즌 | SH1(`demand.shopping_demand_page`)을 5대 축 자리에 둠 — build.py |
| PL1 | 정책·규제: 이슈 / 기관·출처 / 시행·발표일 / 영향 표 | `market_aspect="policy"` 시장 자료(M1에서 분리) |
| CS1 | 소비자 인사이트: 구매 결정 요인 + 페인 포인트 막대 + 원문 카드 | 파생 Fact(P2-7), 세대별 요인 Fact |
| 5-3 | 구매 여정: 단계 × (접점, 상태, 끊기는 곳) | 종합 AI `journey` (P5-1과 공유) |
| 5-4 | 구매 상황 지도: 상황 × 함께 고민하는 브랜드 × 고르는·안 고르는 이유(원문) | 종합 AI `situation` + 소비자 원문 |

규칙(원칙): 숫자는 모두 Fact part(차트 막대·점은 fact_id)로만 들어가고, 자료가 모자라면 장을 만들지 않는다
(P3-6 `min_density`). 각주에는 출처와 n(자료 수)을 적는다. 한 장에는 자사 브랜드를 하나만 둔다.

시장 수치 Fact 계약 (P4-1 수집이 만든다)
- metric: `market_size`(시장 규모) · `market_cagr`(연평균 성장률) · `macro_indicator`(거시 지표: 출국자 수 등)
- unit: "krw" / "usd" / "percent" / "count" 등, period_start~period_end: 수치의 기준 기간
- dims: `segment`(시장 범위, 예: "국내 러기지"), `indicator`(거시 지표 이름), `quote`(원문 문장)
- entity: 시장(카테고리) 이름, evidence_id/source_id: 그 수치가 나온 시장 자료
P4-1 이전에 사람이 확인한 수동 수치(시장 자료 카드에 붙은 percent·amount_krw)는 이름(label)으로
연평균 성장률·시장 규모를 알아볼 수 있을 때만 같은 장에 쓴다.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from typing import Iterable, Optional

from core.composition.cases import _cell_height, _claim_parts, _clean_title, _fit_lines, _height, _publisher
from core.composition.chrome import D, L, M, N, P, T, footnote_block, insight_blocks, lead_block, text_block, title_block
from core.composition.compare import bar_item, fit_bars, sample_note, single_brand, text, usable
from core.composition.demand import _pick_quotes, _voc_pool, quote_cards
from core.composition.formatters import UNIT_FORMATTER
from core.composition.quant import QuantContext, _decorate, _panel_header
from core.composition.tokens import region
from core.metrics.derived import TOPIC_LABEL
from core.schemas.materials import CaseMaterial
from core.schemas.slidespec import (
    BarChartBlock, BarSeries, Block, LineChartBlock, LinePoint, LineSeries, Paragraph, Part, Region, ShapeBlock,
    SlideSpec, TableBlock, TableCell, TableColumn, TableRow,
)

MARKET_METRICS = ("market_size", "market_cagr", "macro_indicator")
CAGR_LABEL = re.compile(r"연평균\s*성장률|CAGR", re.I)
SIZE_LABEL = re.compile(r"시장\s*(규모|거래액)")
UNIT_SUFFIX = {"usd": "달러", "eur": "유로", "cny": "위안", "jpy": "엔", "people": "명", "명": "명"}


# ---------------------------------------------------------------- MK1 시장 규모·성장

def _formatter(fact) -> tuple[str, Optional[str]]:
    """(formatter, unit word after the number) for a market figure."""
    unit = (fact.unit or "").lower()
    if unit in ("percent", "%"):
        return "pct_given", None
    if unit in ("krw", "원"):
        return "krw", None
    if unit in UNIT_FORMATTER:
        return UNIT_FORMATTER[unit], None
    return "int", UNIT_SUFFIX.get(unit, fact.unit if fact.unit not in ("count", "") else None)


def market_kind(fact) -> Optional[str]:
    """size / cagr / macro for a market figure (the P4-1 metric, else a person-checked manual figure's name)."""
    if fact.metric == "market_size":
        return "size"
    if fact.metric == "market_cagr":
        return "cagr"
    if fact.metric == "macro_indicator":
        return "macro"
    label = getattr(fact, "label", None) or ""
    if fact.unit == "percent" and CAGR_LABEL.search(label):
        return "cagr"
    if fact.unit in ("krw", "usd") and SIZE_LABEL.search(label):
        return "size"
    return None


def market_figures(ctx: QuantContext, category: str, materials: list[CaseMaterial]) -> dict[str, list]:
    """Usable market figures for one category: P4-1 facts about the category, and the manual figures on its
    accepted market cards. {"size": [...], "cagr": [...], "macro": [...]}, newest first."""
    accepted = [m for m in materials if m.review_status == "accepted"]
    card_ids = {m.id for m in accepted} | {m.source.id for m in accepted}
    linked = {fid for m in accepted for fid in m.metric_fact_ids}
    brand_ids = {b.id for b in ctx.project.brands}
    out: dict[str, list] = defaultdict(list)
    for f in ctx.metrics.registry.facts.values():
        if not usable(f) or f.brand_id not in brand_ids:
            continue
        ours = f.id in linked or (f.metric in MARKET_METRICS and (
            f.entity == category or f.evidence_id in card_ids or f.source_id in card_ids))
        kind = market_kind(f) if ours else None
        if kind:
            out[kind].append(f)
    for kind in out:
        out[kind].sort(key=lambda f: (f.period_end, f.measured_at, f.id), reverse=True)
    return out


def _figure_name(f) -> str:
    return f.dims.get("segment") or f.dims.get("indicator") or getattr(f, "label", None) or f.entity


def _sources_of(facts: Iterable, materials: list[CaseMaterial]) -> list[tuple[str, Optional[date]]]:
    """(publisher, date) for each figure's source, in first-seen order."""
    by_key = {}
    for m in materials:
        by_key[m.id] = m
        by_key[m.source.id] = m
    out: list[tuple[str, Optional[date]]] = []
    for f in facts:
        m = by_key.get(f.evidence_id or "") or by_key.get(f.source_id or "")
        item = (_publisher(m), m.source.published_at or m.activity_date) if m else (f.source, f.measured_at)
        if item not in out:
            out.append(item)
    return out


def _source_parts(sources: list[tuple[str, Optional[date]]], limit: int = 3) -> list[Part]:
    parts: list[Part] = []
    for i, (name, when) in enumerate(sources[:limit]):
        parts += ([T(" · ")] if i else []) + [N(name)] + ([T(" "), D(when)] if when else [])
    if len(sources) > limit:
        parts.append(T(" 외 "))
        parts += [M(f"{len(sources) - limit}곳", "source_count")]
    return parts


def _tile(i: int, f, x: float, y: float, w: float, h: float, ctx: QuantContext,
          materials: list[CaseMaterial]) -> list[Block]:
    """One big figure: its name, the value, the period it covers (P4-1) or where it was read, the source words."""
    fmt, word = _formatter(f)
    value: list[Part] = [ctx.pf.fact(f, fmt, bold=True, color="navy")] + ([N(" " + word)] if word else [])
    name = _fit_lines(_figure_name(f), w - 28, 10, 2)
    if f.metric in MARKET_METRICS:
        period = [T("기준 "), D(f.period_start)] + ([T("~"), D(f.period_end)] if f.period_end != f.period_start else [])
    else:  # a figure read off a market card: the card's source dates it
        period = _source_parts(_sources_of([f], materials), 1)
    quote = f.dims.get("quote")
    out: list[Block] = [
        ShapeBlock(block_id=f"tile{i}_bg", region=Region(x=x, y=y, w=w, h=h), fill="tint"),
        ShapeBlock(block_id=f"tile{i}_bar", region=Region(x=x, y=y, w=4, h=h), fill="navy"),
        text_block(f"tile{i}_label", "body", Region(x=x + 16, y=y + 10, w=w - 28, h=30), [P(N(name))],
                   spec="card_body", size=10, line=14, weight="semibold"),
        text_block(f"tile{i}_value", "body", Region(x=x + 16, y=y + 42, w=w - 28, h=40), [P(*value)],
                   spec="card_body", size=24, line=30, weight="heavy", valign="m"),
        text(f"tile{i}_period", Region(x=x + 16, y=y + 84, w=w - 28, h=16), period, color="muted", size=8.5),
    ]
    if quote and h >= 150:
        q = _fit_lines(f"“{quote}”", w - 28, 8.5, 2 if h < 190 else 3)
        out.append(text_block(f"tile{i}_quote", "body", Region(x=x + 16, y=y + 104, w=w - 28, h=h - 112),
                              [P(Part(type="quote", text=q))], spec="card_body", size=8.5, line=12, color="subtle"))
    return out


def _evidence_lines(figures: list, materials: list[CaseMaterial], ctx: QuantContext, x: float, y: float, w: float,
                    h: float) -> list[Block]:
    """Under the figures: what their source cards say, in the accepted sentences (one source per line)."""
    by_key = {}
    for m in materials:
        by_key[m.id] = m
        by_key[m.source.id] = m
    cards = list({m.id: m for f in figures
                  if (m := by_key.get(f.evidence_id or "") or by_key.get(f.source_id or ""))}.values())
    paras: list[Paragraph] = []
    for m in cards:
        for c in [c for c in m.claims if c.review_status == "accepted"][:2]:
            para = Paragraph(parts=[*_claim_parts(c, ctx.pf), T(" · "), N(_publisher(m))], bullet="▸")
            if _height(paras + [para], w, "card_body") > h - 30:
                break
            paras.append(para)
    if not paras:
        return []
    return [text_block("evidence_head", "panel_header", Region(x=x, y=y, w=w, h=20), [P(T("수치가 나온 자료의 확인된 문장"))],
                       spec="panel_header", color="navy"),
            ShapeBlock(block_id="evidence_rule", region=Region(x=x, y=y + 23, w=w, h=0), shape="line", line="navy",
                       line_width=1.0),
            text_block("evidence", "body", Region(x=x, y=y + 30, w=w, h=_height(paras, w, "card_body")), paras,
                       spec="card_body")]


def _primary_cagr(cagrs: list, category: str):
    """The growth rate the headline quotes: the whole category's own rate first, not a narrower segment's
    (a P4-1 segment equal to the category, or a manual figure whose name names the category's market)."""
    def rank(f) -> int:
        seg = f.dims.get("segment")
        if seg:
            return 0 if seg == category else 2
        label = getattr(f, "label", None) or ""
        return 0 if category.replace(" ", "") in label.replace(" ", "") else 1 if "시장" in label else 2
    return sorted(cagrs, key=lambda f: (rank(f), -f.period_end.toordinal(), f.id))[0] if cagrs else None


def market_size_page(ctx: QuantContext, category: str, materials: list[CaseMaterial],
                     figures: Optional[dict[str, list]] = None) -> Optional[SlideSpec]:
    """MK1: up to four big figures (시장 규모·연평균 성장률) and, when one indicator has enough points, a macro
    line chart beside them; otherwise the figures take the whole width. No size or growth figure: no page."""
    figs = figures if figures is not None else market_figures(ctx, category, materials)
    big = (figs.get("size") or [])[:2] + (figs.get("cagr") or [])[:4]
    big = big[:4]
    if not big:
        return None
    body = region("body")
    series_by: dict[str, dict[str, object]] = defaultdict(dict)
    for f in figs.get("macro") or []:
        key = f.period_end.isoformat()[:7] if f.period_end.month != 12 or f.period_start.month != 1 else str(f.period_end.year)
        series_by[_figure_name(f)].setdefault(key, f)
    macro_name, macro_pts = max(series_by.items(), key=lambda kv: (len(kv[1]), kv[0]), default=(None, {}))
    has_line = len(macro_pts) >= ctx.config.line_chart_min_points
    fact_ids: list[str] = []
    blocks: list[Block] = []
    tiles_w = body.w * 0.5 if has_line else body.w
    cols = 2 if (has_line or len(big) == 4) else len(big)
    rows = math.ceil(len(big) / cols)
    gap = 16
    tw = (tiles_w - gap * (cols - 1)) / cols
    th = min(200.0 if has_line else 170.0, (body.h - 44 - gap * (rows - 1)) / rows)
    blocks += _panel_header("tiles_header", body.x, body.y, tiles_w, [T("시장 규모·성장률")])
    for i, f in enumerate(big):
        r, c = divmod(i, cols)
        blocks += _tile(i, f, body.x + c * (tw + gap), body.y + 44 + r * (th + gap), tw, th, ctx, materials)
        fact_ids.append(f.id)
    tiles_bottom = body.y + 44 + rows * th + gap * (rows - 1)
    if not has_line and body.y + body.h - tiles_bottom >= 90:
        blocks += _evidence_lines(big, materials, ctx, body.x, tiles_bottom + 20, body.w, body.y + body.h - tiles_bottom - 20)
    if has_line:
        keys = sorted(macro_pts)
        lx, lw = body.x + tiles_w + 32, body.w - tiles_w - 32
        blocks += _panel_header("line_header", lx, body.y, lw, [N(macro_name)])
        label = (lambda k: f"{k[2:4]}.{k[5:7]}") if len(keys[0]) > 4 else (lambda k: k)
        series = [LineSeries(entity=macro_name, role="self", points=[
            LinePoint(month=k, fact_id=macro_pts[k].id, value=float(macro_pts[k].value)) for k in keys])]
        blocks.append(LineChartBlock(block_id="macro", region=Region(x=lx, y=body.y + 44, w=lw, h=body.h - 44),
                                     categories=[label(k) for k in keys], series=series))
        fact_ids += [macro_pts[k].id for k in keys]
    cagr = _primary_cagr(figs.get("cagr") or [], category)
    size = (figs.get("size") or [None])[0]
    if cagr is not None:
        lead = [N(category), T(" 시장, 연 "), ctx.pf.fact(cagr, "pct_given", bold=True), T(" 성장 전망")]
    else:
        fmt, word = _formatter(size)
        lead = [N(category), T(" 시장 규모 "), ctx.pf.fact(size, fmt, bold=True)] + ([N(" " + word)] if word else [])
    insights = []
    if cagr is not None:
        insights.append(([T("성장 속도")], [N(_figure_name(cagr)), T(" 연평균 "), ctx.pf.fact(cagr, "pct_given", bold=True)]))
    if size is not None:
        fmt, word = _formatter(size)
        insights.append(([T("시장 규모")], [N(_figure_name(size)), T(" "), ctx.pf.fact(size, fmt, bold=True)]
                         + ([N(" " + word)] if word else [])))
    fastest = max(figs.get("cagr") or [], key=lambda f: f.value, default=None)
    if fastest is not None and fastest is not cagr:
        insights.append(([T("가장 빠른 부문")], [N(_figure_name(fastest)), T(" 연평균 "),
                                              ctx.pf.fact(fastest, "pct_given", bold=True)]))
    elif has_line:
        last = macro_pts[sorted(macro_pts)[-1]]
        fmt, word = _formatter(last)
        insights.append(([N(macro_name)], [T("최근 "), ctx.pf.fact(last, fmt, bold=True)] + ([N(" " + word)] if word else [])))
    shown = big + ([macro_pts[k] for k in macro_pts] if has_line else [])
    sources = _sources_of(shown, materials)
    foot = [T("*출처 "), *_source_parts(sources), T(" · "), M(f"수치 {len(shown)}개 · 출처 {len(sources)}곳", "sample"),
            T(" · 원문 문장과 대조해 확인한 값, 정의가 다른 수치는 한 축으로 합치지 않음")]
    if not any(p.type == "date" for p in foot):
        foot += [T(" · 측정 "), D(max(f.measured_at for f in shown))]
    blocks = [title_block("Market", "시장 규모·성장"), lead_block([P(*lead)]), *blocks,
              *insight_blocks(insights[:3]), footnote_block([P(*foot)])]
    return SlideSpec(slide_id="MK1", template_id="market_size.v1", page_role="content", section_id="campaign",
                     title="시장 규모·성장", blocks=_decorate(ctx, blocks), needs_review=True, is_data=True)


# ---------------------------------------------------------------- PL1 정책·규제

def policy_materials(materials: list[CaseMaterial]) -> list[CaseMaterial]:
    return [m for m in materials if m.market_aspect == "policy" and m.review_status == "accepted"
            and any(c.review_status == "accepted" for c in m.claims)]


def policy_pages(materials: list[CaseMaterial], pf, badge: list[Block], category: Optional[str] = None) -> list[SlideSpec]:
    """PL1: one row per accepted policy note — 이슈 / 기관·출처 / 시행·발표일 / 영향 (its accepted sentences)."""
    rows_src = sorted(policy_materials(materials),
                      key=lambda m: (str(m.activity_date or m.source.published_at or ""), m.id), reverse=True)
    if not rows_src:
        return []
    columns = [TableColumn(key="issue", label="이슈", width=0.24, align="l"),
               TableColumn(key="org", label="기관·출처", width=0.16),
               TableColumn(key="date", label="시행·발표일", width=0.13),
               TableColumn(key="impact", label="영향", width=0.47, align="l")]
    built = []
    for m in rows_src:
        issue = [P(N(m.event_name or _clean_title(m.title, m.entity)), bold=True)]
        org = [P(N(_publisher(m)))]
        if m.activity_date:
            when = [P(T("시행 "), D(m.activity_date))]
        elif m.source.published_at:
            when = [P(T("발표 "), D(m.source.published_at))]
        else:
            when = [P(T("—"))]
        impact = [Paragraph(parts=_claim_parts(c, pf), bullet="→" if c.kind != "fact" else "▸",
                            color="navy" if c.kind != "fact" else None, bold=c.kind != "fact")
                  for c in m.claims if c.review_status == "accepted"][:3]
        if m.source.url:
            impact.append(P(L("원문 보기", m.source.url)))
        cells = [TableCell(paragraphs=issue, align="l"), TableCell(paragraphs=org), TableCell(paragraphs=when),
                 TableCell(paragraphs=impact, align="l")]
        h = max(_cell_height(cell.paragraphs, 1184 * col.width - 12, 10) for col, cell in zip(columns, cells))
        built.append((m, TableRow(cells=cells, ref=m.id), max(48, math.ceil(h + 10))))
    limit = 400  # table body above the insight row
    chunks, cur, used = [], [], 0
    for item in built:
        if cur and max(used, item[2]) * (len(cur) + 1) > limit:
            chunks.append(cur)
            cur, used = [], 0
        cur.append(item)
        used = max(used, item[2])
    chunks.append(cur)
    slides = []
    for i, chunk in enumerate(chunks):
        # rows share the body down to the insight row instead of leaving its lower half empty (P3-5 layout)
        row_h = max(max(r[2] for r in chunk), min(120, (limit - 32) // len(chunk)))
        table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=32 + row_h * len(chunk)),
                           columns=columns, rows=[r[1] for r in chunk], row_height=row_h, header_height=32,
                           size=10, header_size=10)
        shown = [r[0] for r in chunk]
        sub_parts = [T("정책·규제")] + ([T(" "), M(f"({i + 1}/{len(chunks)})", "page")] if len(chunks) > 1 else [])
        lead = [N(category), T(" 시장에 걸린 정책·규제 — 시행 시점과 영향")] if category else [T("시장에 걸린 정책·규제 — 시행 시점과 영향")]
        insights = []
        for m in shown:
            pick = next((c for c in m.claims if c.review_status == "accepted" and c.kind != "fact"), None)
            if pick is not None and len(insights) < 3:
                insights.append(([N(_fit_lines(m.event_name or _clean_title(m.title, m.entity), 340, 10.5, 1))],
                                 _claim_parts(pick, pf)))
        dates = sorted(d for d in (m.activity_date or m.source.published_at
                                   or (m.source.fetched_at.date() if m.source.fetched_at else None) for m in shown) if d)
        foot = [T("*각 행 출처 기준")]
        if dates:
            foot += [T(" · "), D(dates[0])] + ([T("~"), D(dates[-1])] if dates[-1] != dates[0] else [])
        foot += [T(" · "), M(f"자료 {len(shown)}건", "sample"), T(" · 시행일이 없는 항목은 발표일")]
        blocks = [title_block("Market", sub_parts=sub_parts), lead_block([P(*lead)]), table,
                  *(insight_blocks(insights) if i == 0 else []), footnote_block([P(*foot)]), *badge]
        slides.append(SlideSpec(slide_id="PL1" + (f"-p{i + 1}" if i else ""), template_id="policy_table.v1",
                                page_role="content", section_id="campaign", title="정책·규제", blocks=blocks,
                                source_ids=[m.source.id for m in shown], needs_review=True, is_data=True,
                                parent_slide_id="PL1" if i else None))
    return slides


# ---------------------------------------------------------------- CS1 소비자 인사이트

CS_MIN_BARS = 3
GEN_COLORS = ["navy", "red", "line_other"]


def _factor_chart(ctx: QuantContext, brand, reg: Region) -> tuple[list[Block], list[str], Optional[tuple]]:
    """세대별 구매 결정 요인 (purchase_factor_share: dims generation, factor) when two or more generations
    have it; else the topics consumers raise in their own posts (voc_topic_share). Returns blocks, fact ids and
    (title, body) for the top factor."""
    by_gen: dict[str, dict[str, object]] = defaultdict(dict)
    for f in sorted((f for f in ctx.metrics.registry.facts.values()
                     if f.metric == "purchase_factor_share" and f.brand_id == brand.id and f.entity == brand.name
                     and usable(f)), key=lambda f: (f.measured_at, f.id), reverse=True):
        if f.dims.get("generation") and f.dims.get("factor"):
            by_gen[f.dims["generation"]].setdefault(f.dims["factor"], f)
    gens = sorted(by_gen)[:3]
    if len(gens) >= 2:
        totals: dict[str, float] = defaultdict(float)
        for g in gens:
            for k, f in by_gen[g].items():
                totals[k] += float(f.value)
        factors = sorted(totals, key=lambda k: (-totals[k], k))[:5]
        if len(factors) >= CS_MIN_BARS:
            series = [BarSeries(name=g, color=GEN_COLORS[i], items=[
                bar_item(ctx, g, k, by_gen[g][k], "share") if k in by_gen[g] else None for k in factors])
                for i, g in enumerate(gens)]
            chart = BarChartBlock(block_id="factors", region=Region(x=reg.x, y=reg.y + 44, w=reg.w, h=reg.h - 44),
                                  categories=factors, series=series, number_format='0"%"', unit="percent",
                                  label_size=9, gap_width=60)
            g0 = gens[0]
            top_k, top_f = max(by_gen[g0].items(), key=lambda kv: kv[1].value)
            return ([*_panel_header("factors_header", reg.x, reg.y, reg.w, [T("세대별 구매 결정 요인(%)")]), chart],
                    [it.fact_id for it in chart.bar_items()],
                    ([N(g0), T(" 결정 요인")], [N(top_k), T(" "), ctx.pf.fact(top_f, "share", bold=True)]))
    topics = {}
    for f in sorted((f for f in ctx.metrics.registry.facts.values()
                     if f.metric == "voc_topic_share" and f.brand_id == brand.id and f.entity == brand.name and usable(f)),
                    key=lambda f: (f.measured_at, f.id), reverse=True):
        if f.dims.get("topic") not in (None, "other"):
            topics.setdefault(f.dims["topic"], f)
    ranked = sorted(topics.items(), key=lambda kv: (-kv[1].value, kv[0]))[:5]
    if len(ranked) < CS_MIN_BARS:
        return [], [], None
    items = [bar_item(ctx, brand.name, TOPIC_LABEL.get(k, k), f, "share", "key" if i == 0 else "self")
             for i, (k, f) in enumerate(ranked)]
    chart = BarChartBlock(block_id="factors", region=fit_bars(Region(x=reg.x, y=reg.y + 44, w=reg.w, h=reg.h - 44),
                                                                len(items)),
                          items=items, number_format='0.0"%"', unit="percent", label_size=10, gap_width=55)
    k, f = ranked[0]
    return ([*_panel_header("factors_header", reg.x, reg.y, reg.w, [T("원문에서 말한 구매 고려 요인(%)")]), chart],
            [it.fact_id for it in chart.bar_items()],
            ([T("가장 많이 말한 요인")], [N(TOPIC_LABEL.get(k, k)), T(" "), ctx.pf.fact(f, "share", bold=True)]))


def consumer_insight_page(ctx: QuantContext, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    """CS1: 구매 결정 요인 | 페인 포인트 상위 5 | 대표 원문 — one self brand. Needs both charts (3+ bars each)."""
    brand = single_brand(ctx)
    if brand is None:
        return None
    pains: dict[str, object] = {}
    for f in sorted((f for f in ctx.metrics.registry.facts.values()
                     if f.metric == "pain_point_count" and f.brand_id == brand.id and f.entity == brand.name and usable(f)),
                    key=lambda f: (f.measured_at, f.id), reverse=True):
        if f.dims.get("pain_point"):
            pains.setdefault(f.dims["pain_point"], f)
    ranked = sorted(pains.items(), key=lambda kv: (-kv[1].value, kv[0]))[:5]
    if len(ranked) < CS_MIN_BARS:
        return None
    body = region("body")
    quotes = _pick_quotes(_voc_pool(materials, brand.name), 3)
    col_w = (body.w - 64) / 3 if quotes else (body.w - 32) / 2
    factor_blocks, fact_ids, factor_insight = _factor_chart(ctx, brand, Region(x=body.x, y=body.y, w=col_w, h=body.h))
    if not factor_blocks:
        return None
    px = body.x + col_w + 32
    items = [bar_item(ctx, brand.name, name, f, "count", "key" if i == 0 else "self") for i, (name, f) in enumerate(ranked)]
    pain_chart = BarChartBlock(block_id="pains", region=fit_bars(Region(x=px, y=body.y + 44, w=col_w, h=body.h - 44),
                                                                   len(items)),
                               items=items, number_format='#,##0"건"', unit="count", label_size=10, gap_width=55)
    blocks: list[Block] = [*factor_blocks, *_panel_header("pains_header", px, body.y, col_w, [T("불만 표현별 원문 수")]),
                           pain_chart]
    fact_ids += [it.fact_id for it in pain_chart.bar_items()]
    if quotes:
        qx = px + col_w + 32
        blocks += _panel_header("quote_header", qx, body.y, col_w, [T("대표 원문")])
        blocks += quote_cards(quotes, qx, body.y + 44, col_w, body.h - 44)
    top_name, top = ranked[0]
    insights = [factor_insight, ([T("가장 큰 불편")], [N(top_name), T(" 원문 "), ctx.pf.fact(top, "count", bold=True), T("건")])]
    if len(ranked) > 1:
        name2, f2 = ranked[1]
        insights.append(([T("다음 불편")], [N(name2), T(" 원문 "), ctx.pf.fact(f2, "count", bold=False), T("건")]))
    from core.composition.compare import footnote
    samples = [ctx.metrics.registry.facts[i] for i in fact_ids if i in ctx.metrics.registry.facts]
    lead = lead_block([P(N(brand.name), T(" 소비자가 사는 이유와 불편 — 구매 결정 요인, 페인 포인트, 원문"))])
    blocks = [title_block("Customer", "소비자 인사이트"), lead, *blocks, *insight_blocks(insights),
              footnote(ctx, fact_ids, [T("채택한 소비자 원문·댓글(협찬·체험단 제외)")], sample_note(samples, "원문"))]
    return SlideSpec(slide_id="CS1", template_id="consumer_insight.v1", page_role="content", section_id="voc",
                     title="소비자 인사이트", blocks=_decorate(ctx, blocks), source_ids=[m.source.id for m in quotes],
                     needs_review=True, is_data=True)


# ---------------------------------------------------------------- 5-3 구매 여정 · 5-4 구매 상황 지도 (종합 AI)

def _ref_part(row: dict) -> list[Part]:
    ref = row.get("ref")
    if not ref:
        return []
    return [T(" "), L(f"[{ref}]", row["source_url"]) if row.get("source_url") else M(f"[{ref}]", "slide_ref")]


def _table_page(slide_id: str, template: str, sub: str, lead: str, columns: list[TableColumn],
                rows: list[list[list[Paragraph]]], foot: list[Part], size: float = 10) -> SlideSpec:
    body = region("body")
    table_rows, hs = [], []
    for cells in rows:
        tc = [TableCell(paragraphs=paras, align=col.align) for col, paras in zip(columns, cells)]
        hs.append(max(_cell_height(c.paragraphs, body.w * col.width - 12, size) for col, c in zip(columns, tc)))
        table_rows.append(TableRow(cells=tc))
    row_h = max(44, math.ceil(max(hs) + 12), min(130, (body.h + 40 - 32) // max(1, len(rows))))
    table = TableBlock(block_id="table", region=Region(x=body.x, y=body.y, w=body.w, h=32 + row_h * len(rows)),
                       columns=columns, rows=table_rows, row_height=row_h, header_height=32, size=size, header_size=size)
    blocks = [title_block("Customer", sub), lead_block([P(T(lead))]), table, footnote_block([P(*foot)])]
    return SlideSpec(slide_id=slide_id, template_id=template, page_role="content", section_id="voc", title=sub,
                     blocks=blocks, is_data=False, needs_review=True)


def journey_page(data: dict) -> Optional[SlideSpec]:
    """5-3: 단계 × (접점, 상태, 끊기는 곳), each row citing the body page it was read from."""
    stages = [s for s in (data.get("stages") or []) if s.get("stage")][:6]
    if len(stages) < 3:
        return None
    columns = [TableColumn(key="stage", label="단계", width=0.14), TableColumn(key="touch", label="접점", width=0.26, align="l"),
               TableColumn(key="state", label="소비자 상태", width=0.30, align="l"),
               TableColumn(key="drop", label="끊기는 곳", width=0.30, align="l")]
    rows = [[[P(T(s["stage"]), bold=True)] + ([P(*_ref_part(s)[1:], color="muted")] if s.get("ref") else []),
             [P(T(s.get("touchpoint", "")))], [P(T(s.get("state", "")))],
             [P(T(s.get("drop") or "—"), color="red" if s.get("drop") else "muted")]] for s in stages]
    return _table_page("5-3", "purchase_journey.v1", "구매 여정", data.get("lead") or "구매 여정 — 단계별 접점과 끊기는 곳",
                       columns, rows, [T("*본문 장표에서 읽힌 내용을 AI가 단계별로 정리 · [ ]는 근거 장표")])


def situation_page(data: dict) -> Optional[SlideSpec]:
    """5-4: 상황 × 함께 고민하는 브랜드 × 고르는 이유·안 고르는 이유 — the reasons are verbatim consumer words."""
    rows_src = [r for r in (data.get("rows") or []) if r.get("situation") and (r.get("pick") or r.get("skip"))][:5]
    if len(rows_src) < 2:
        return None

    def quote(q: Optional[dict]) -> list[Paragraph]:
        if not q:
            return [P(T("—"), color="muted")]
        words = Part(type="quote", text=f"“{q['text']}”")
        tail = [P(L(q.get("site") or "원문", q["url"]), color="muted")] if q.get("url") else []
        return [P(words)] + tail

    columns = [TableColumn(key="situation", label="구매 상황", width=0.18, align="l"),
               TableColumn(key="brands", label="함께 고민하는 브랜드", width=0.18),
               TableColumn(key="pick", label="고르는 이유(원문)", width=0.32, align="l"),
               TableColumn(key="skip", label="안 고르는 이유(원문)", width=0.32, align="l")]
    rows = [[[P(T(r["situation"]), bold=True)], [P(N(" · ".join(r.get("brands") or [])))], quote(r.get("pick")),
             quote(r.get("skip"))] for r in rows_src]
    n = len({q["url"] for r in rows_src for q in (r.get("pick"), r.get("skip")) if q and q.get("url")})
    dates = sorted(d for r in rows_src for q in (r.get("pick"), r.get("skip")) if q and (d := q.get("date")))
    foot: list[Part] = [T("*채택한 소비자 원문(협찬 제외)에서 AI가 상황별로 고른 문장 · "), M(f"원문 {n}건", "sample")]
    if dates:
        foot += [T(" · "), D(date.fromisoformat(dates[0]))] + ([T("~"), D(date.fromisoformat(dates[-1]))] if dates[-1] != dates[0] else [])
    return _table_page("5-4", "purchase_situation.v1", "구매 상황 지도",
                       data.get("lead") or "구매 상황 지도 — 상황마다 함께 고민하는 브랜드와 고르는 이유",
                       columns, rows, foot, size=9.5)
