"""Quantitative templates: 2-8a search_share, 2-8b search_trend, 2-8c combo_share,
2-8d target_table, 3-1 creator_table, 5 recap (PRD 11; QUALITY_BASELINE p.26/27/29/40/89).

Leads come only from Findings whose entities/windows/cat are visible on the page, and a
lead may only cite numbers that the page body also displays (PRD 11, QC 12).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from core.composition.chrome import (
    D, M, N, P, PERIOD, PartFactory, T, circled, footnote_block, lead_block, synthetic_badge, takeaway_block,
    text_block, title_block,
)
from core.composition.formatters import fmt_month_label, fmt_month_range
from core.composition.measure import height_at, text_width
from core.composition.tokens import region, type_spec
from core.decimalx import quantize
from core.metrics.engine import MetricsResult, PostMetrics, ShareTable
from core.rules.config import RulesConfig
from core.schemas.facts import Finding
from core.schemas.materials import AssetRef
from core.schemas.project import Project
from core.schemas.slidespec import (
    BarChartBlock, BarItem, Block, Crop, ImageBlock, LineChartBlock, LinePoint, LineSeries, Paragraph, Region,
    ShapeBlock, SlideSpec, TableBlock, TableCell, TableColumn, TableRow, TextBlock,
)

SOURCE_LABELS = {"synthetic_fixture": "합성 테스트 자료(synthetic_fixture)", "posts.csv": "게시물 입력 자료",
                 "scrapecreators": "공개 게시물 관측값(ScrapeCreators)"}


@dataclass
class QuantContext:
    project: Project
    metrics: MetricsResult
    findings: list[Finding]
    pf: PartFactory
    config: RulesConfig
    synthetic: bool
    influencer_assets: dict[str, AssetRef] = field(default_factory=dict)  # brand_id -> accepted asset
    used_leads: set[str] = field(default_factory=set)

    def brand_name(self, brand_id: str) -> str:
        return self.project.brand(brand_id).name


# ---------------------------------------------------------------- helpers

def _pick_finding(ctx: QuantContext, brand_ids: list[str], rule_ids: set[str], entities_shown: dict[str, set[str]],
                  windows_shown: set[str], cat: Optional[str] = None) -> Optional[Finding]:
    """Highest-strength unused Finding that fits what the page actually shows."""
    for f in ctx.findings:  # already sorted by strength
        if f.rule_id not in rule_ids or f.brand_id not in brand_ids or f.id in ctx.used_leads:
            continue
        if f.cat != cat:
            continue
        if not set(f.entities) <= entities_shown.get(f.brand_id, set()):
            continue
        if not set(f.windows) <= windows_shown:
            continue
        ctx.used_leads.add(f.id)
        return f
    return None


def _pick_findings(ctx: QuantContext, brand_ids: list[str], rule_ids: set[str], entities_shown: dict[str, set[str]],
                   windows_shown: set[str], cat: Optional[str] = None, limit: int = 3) -> list[Finding]:
    """Up to `limit` unused Findings that fit what the page shows, at most one per brand
    (highest-strength first) — the real-data source for a page's ①②③ numbered insights."""
    out: list[Finding] = []
    seen_brands: set[str] = set()
    for f in ctx.findings:
        if len(out) >= limit:
            break
        if f.rule_id not in rule_ids or f.brand_id not in brand_ids or f.id in ctx.used_leads:
            continue
        if f.brand_id in seen_brands:
            continue
        if f.cat != cat:
            continue
        if not set(f.entities) <= entities_shown.get(f.brand_id, set()):
            continue
        if not set(f.windows) <= windows_shown:
            continue
        ctx.used_leads.add(f.id)
        seen_brands.add(f.brand_id)
        out.append(f)
    return out


def _sources_for(ctx: QuantContext, fact_ids: list[str]) -> list[str]:
    names: list[str] = []
    for fid in fact_ids:
        for raw in ctx.metrics.registry.lineage(fid):
            src = ctx.metrics.registry.facts[raw].source
            label = SOURCE_LABELS.get(src, src)
            if label not in names:
                names.append(label)
    return names


def _measured(ctx: QuantContext, fact_ids: list[str]) -> Optional[date]:
    dates = [ctx.metrics.registry.facts[r].measured_at for fid in fact_ids for r in ctx.metrics.registry.lineage(fid)]
    return max(dates) if dates else None


def _panel_xs(n: int, single: float = 640) -> tuple[list[float], float]:
    width = {1: single, 2: 540, 3: 360}[n]
    gap = {1: 0, 2: 60, 3: 60}[n]
    total = n * width + (n - 1) * gap
    start = 640 - total / 2
    return [start + i * (width + gap) for i in range(n)], width


def _panel_header(block_id: str, x: float, y: float, w: float, text: list) -> list[Block]:
    spec = type_spec("panel_header")
    need = text_width("".join(p.rendered() for p in text), spec["size"], bold=True) + 36
    hw = min(w, max(need, min(w * 0.62, 340)))
    hx = x + (w - hw) / 2
    reg = Region(x=hx, y=y, w=hw, h=36)
    return [
        ShapeBlock(block_id=f"{block_id}_bg", region=reg, shape="rounded", fill="panel_header"),
        text_block(block_id, "panel_header", reg, [P(*text)], spec="panel_header", align="c", valign="m",
                   color="white", bold=True),
    ]


def _bar_metrics(n_panels: int, n_items: int) -> tuple[float, float]:
    """(row height per bar, label pt). Fewer panels/bars get larger bars instead of empty space."""
    if n_panels == 1 and n_items <= 6:
        return 58.0, 12.0
    if n_panels <= 2 and n_items <= 6:
        return 50.0, 11.0
    return 40.0, 10.0


def _bar_value(v: Decimal) -> float:
    return float(quantize(v, 1))


def _footnote(ctx: QuantContext, fact_ids: list[str], *extra: list) -> TextBlock:
    parts = [T("*")]
    for chunk in extra:
        parts += chunk + [T(" · ")]
    measured = _measured(ctx, fact_ids)
    if measured:
        parts += [T("측정 "), D(measured), T(" · ")]
    parts += [T(" · ".join(_sources_for(ctx, fact_ids)))]
    return footnote_block([P(*parts)])


def _decorate(ctx: QuantContext, blocks: list[Block]) -> list[Block]:
    return blocks + ([synthetic_badge()] if ctx.synthetic else [])


def _neutral_lead(*parts) -> TextBlock:
    return lead_block([P(*parts)])


def _vstack_top(total_h: float) -> float:
    body = region("body")
    return body.y + max(0.0, (body.h - total_h) / 2)


# ---------------------------------------------------------------- 2-8a

def search_share(ctx: QuantContext) -> Optional[SlideSpec]:
    cfg = ctx.config
    tables = [(b, ctx.metrics.find_share(b.id, cfg.long_window, "all")) for b in ctx.project.brands]
    tables = [(b, t) for b, t in tables if t is not None][:3]
    if not tables:
        return None
    shown = {b.id: set(t.entities) for b, t in tables}
    windows = {cfg.long_window} | {cfg.main_window for b, _ in tables
                                   if ctx.metrics.find_share(b.id, cfg.main_window, "all")}
    findings = _pick_findings(ctx, [b.id for b, _ in tables], {"RULE-R04"}, shown, windows)
    finding = findings[0] if findings else None

    xs, w = _panel_xs(len(tables))
    n_items = max(len(t.entities) for _, t in tables)
    row_h, label_pt = _bar_metrics(len(tables), n_items)
    chart_h = n_items * row_h + 16
    total = 36 + 12 + chart_h + 6 + 44
    top = _vstack_top(total)
    blocks: list[Block] = []
    fact_ids: list[str] = []
    for i, ((brand, table), x) in enumerate(zip(tables, xs)):
        r04 = next((f for f in ctx.findings if f.rule_id == "RULE-R04" and f.brand_id == brand.id), None)
        key = r04.rival if r04 else None
        cat_label = brand.categories[0] if brand.categories else "브랜드명"
        blocks += _panel_header(f"panel{i}_header", x, top, w, [N(brand.name), T(f" 세트 · {cat_label} (%)")])
        items = [BarItem(entity=e, label=e, fact_id=table.shares[e].id, display=ctx.pf.fact(table.shares[e], "share").display,
                         value=_bar_value(table.share(e)),
                         role="self" if e == brand.name else ("key" if e == key else "other"))
                 for e in table.ordered()]
        blocks.append(BarChartBlock(block_id=f"panel{i}_chart", region=Region(x=x, y=top + 48, w=w, h=chart_h), items=items,
                                    label_size=label_pt))
        fact_ids += [it.fact_id for it in items]
        caption: list[Paragraph] = []
        main = ctx.metrics.find_share(brand.id, cfg.main_window, "all")
        if main:
            other = key or next(e for e in main.ordered() if e != brand.name)
            caption.append(P(M(cfg.main_window, "window"), T(" "), N(brand.name), T(" "), ctx.pf.fact(main.shares[brand.name], "share", bold=False),
                             T(" · "), N(other), T(" "), ctx.pf.fact(main.shares[other], "share", bold=False)))
            fact_ids += [main.shares[brand.name].id, main.shares[other].id]
        if r04:
            g12, g9 = r04.fact_ids[0], r04.fact_ids[1]
            caption.append(P(N(r04.rival or ""), T(" 대비 격차 "), M(cfg.long_window, "window"), T(" "), ctx.pf.fact(g12, "gap"),
                             T(" → "), M(cfg.main_window, "window"), T(" "), ctx.pf.fact(g9, "gap")))
            fact_ids += [g12, g9]
        blocks.append(text_block(f"panel{i}_caption", "caption", Region(x=x, y=top + 48 + chart_h + 6, w=w, h=44),
                                 caption, spec="caption", align="c"))

    def _rivalry_parts(f: Finding, *, emphasize: bool = True) -> list:
        s = f.summary
        return [N(ctx.brand_name(f.brand_id)), T("의 "), N(s["rival"]), T(" 대비 "),
                T("브랜드 검색 점유 우위 축소", bold=emphasize), T(" — 격차 "), M(cfg.long_window, "window"), T(" "),
                ctx.pf.fact(f.fact_ids[0], "gap"), T(" → "), M(cfg.main_window, "window"), T(" "),
                ctx.pf.fact(f.fact_ids[1], "gap")]

    if finding:
        lead = _neutral_lead(*_rivalry_parts(finding))
    else:
        lead = _neutral_lead(T("브랜드별 경쟁 세트 안의 브랜드명 검색 점유 — "), M("12개월", "window"), T(" 기준"))
    # Plain (non-bold) parts here: the height estimate below assumes one uniform weight per line.
    insights = [Paragraph(parts=_rivalry_parts(f, emphasize=False), bullet=circled(i)) for i, f in enumerate(findings)]
    for f in findings:
        fact_ids += list(f.fact_ids)
    insight_block = None
    if insights:
        isize, iline = 11.5, 17.0
        iy = top + total + 10
        needed = height_at(insights, 1200, isize, iline)
        if iy + needed + 8 <= 572:  # skip rather than clamp — a shrunk box still overflows at render
            insight_block = text_block("insights", "body", Region(x=40, y=iy, w=1200, h=needed), insights,
                                       spec="card_body", size=isize, line=iline, editable=True)
    t0 = tables[0][1]
    main0 = ctx.metrics.find_share(tables[0][0].id, cfg.main_window, "all")
    period_parts = [M(cfg.long_window, "window"), T(" "), PERIOD(t0.period_start, t0.period_end)]
    if main0:
        period_parts += [T(" · "), M(cfg.main_window, "window"), T(" "), PERIOD(main0.period_start, main0.period_end)]
    kw = " · ".join(f"{g.entity}({'·'.join(g.keywords)})" for b, _ in tables for g in b.keyword_groups)
    blocks = [
        title_block("Search", sub_parts=[T("브랜드명 검색 점유 — "), M("12개월", "window"), T(" (브랜드별 경쟁 세트)")]),
        lead, *blocks,
        *([insight_block] if insight_block else []),
        takeaway_block(P(T("점유는 브랜드별 경쟁 세트 내부 비중", bold=True),
                         T(" — 검색어 그룹 상대 지수 합 기준(절대 검색량 아님), 세트 간 수치는 직접 비교하지 않음"), bullet="▶")),
        _footnote(ctx, fact_ids, period_parts, [T("세트 내 지수 합 비율(상대지수)")] + ([T(" · 검색어 그룹: " + kw)] if kw else [])),
    ]
    return SlideSpec(slide_id="2-8a", template_id="search_share.v1", page_role="content", section_id="search",
                     title="브랜드명 검색 점유", blocks=_decorate(ctx, blocks),
                     finding_ids=[f.id for f in findings], needs_review=not findings, is_data=True)


# ---------------------------------------------------------------- 2-8b

def search_trend(ctx: QuantContext) -> Optional[SlideSpec]:
    cfg = ctx.config
    panels = []
    for b in ctx.project.brands:
        series = ctx.metrics.monthly_for(b.id, "all")
        if not series:
            continue
        main = ctx.metrics.find_share(b.id, cfg.main_window, "all")
        comps = [c for c in b.competitors if c in series.values]
        if main:
            comps.sort(key=lambda c: -main.share(c))  # 9M top competitors
        panels.append((b, series, comps[:3]))
    panels = panels[:3]
    if not panels:
        return None
    shown = {b.id: {b.name, *comps} for b, _, comps in panels}
    findings = _pick_findings(ctx, [b.id for b, _, _ in panels], {"RULE-R03"}, shown, {"monthly"})
    finding = findings[0] if findings else None

    xs, w = _panel_xs(len(panels), single=820)
    chart_h = 270
    total = 36 + 8 + chart_h + 6 + 44
    top = _vstack_top(total)
    blocks: list[Block] = []
    fact_ids: list[str] = []
    for i, ((brand, series, comps), x) in enumerate(zip(panels, xs)):
        r03 = [f for f in ctx.findings if f.rule_id == "RULE-R03" and f.brand_id == brand.id and f.rival in comps]
        key = r03[0].rival if r03 else None
        seg_label = "전체"
        blocks += _panel_header(f"panel{i}_header", x, top, w, [N(brand.name), T(f" vs 경쟁사 · {seg_label}")])
        roles = {}
        others = iter(["other", "other2", "other2"])
        for c in comps:
            roles[c] = "key" if c == key else next(others)
        line_series = []
        for e in [brand.name, *comps]:
            pts = []
            for m in series.months:
                f = series.values.get(e, {}).get(m)
                pts.append(LinePoint(month=m, fact_id=f.id if f else None, value=float(f.value) if f else None))
            line_series.append(LineSeries(entity=e, role="self" if e == brand.name else roles[e], points=pts))
        blocks.append(LineChartBlock(block_id=f"panel{i}_chart", region=Region(x=x, y=top + 44, w=w, h=chart_h),
                                     categories=[fmt_month_label(m) for m in series.months], series=line_series))
        caption: list[Paragraph] = []
        last = series.months[-1]
        rival = key or (comps[0] if comps else None)
        own_last = series.values[brand.name].get(last)
        riv_last = series.values.get(rival, {}).get(last) if rival else None
        if own_last and riv_last:
            caption.append(P(M(fmt_month_label(last), "month"), T(" "), N(brand.name), T(" "), ctx.pf.fact(own_last, "index", bold=False),
                             T(" vs "), N(rival), T(" "), ctx.pf.fact(riv_last, "index", bold=False)))
            fact_ids += [own_last.id, riv_last.id]
        if r03:
            s = r03[0].summary
            caption.append(P(N(s["rival"]), T(" 우위 구간 "), D(fmt_month_range(s["start_month"], s["end_month"])), T(" · "),
                             ctx.pf.fact(r03[0].fact_ids[0], "months")))
            fact_ids.append(r03[0].fact_ids[0])
        blocks.append(text_block(f"panel{i}_caption", "caption", Region(x=x, y=top + 44 + chart_h + 6, w=w, h=44),
                                 caption, spec="caption", align="c"))
        fact_ids += [p.fact_id for s in line_series for p in s.points if p.fact_id]

    def _trend_parts(f: Finding, *, emphasize: bool = True) -> list:
        s = f.summary
        return [N(s["rival"]), T(", "), D(fmt_month_range(s["start_month"], s["end_month"])), T(" "),
                ctx.pf.fact(f.fact_ids[0], "months"), T(" 연속 "), N(ctx.brand_name(f.brand_id)),
                T(" 검색 지수 상회 — "), T("경쟁사 검색 지수 우위 구간 지속", bold=emphasize)]

    if finding:
        lead = _neutral_lead(*_trend_parts(finding))
    else:
        lead = _neutral_lead(T("자사와 경쟁사의 월별 검색 지수 추이"))
    insights = [Paragraph(parts=_trend_parts(f, emphasize=False), bullet=circled(i)) for i, f in enumerate(findings)]
    for f in findings:
        fact_ids += list(f.fact_ids)
    insight_block = None
    if insights:
        isize, iline = 11.5, 17.0
        iy = top + total + 10
        needed = height_at(insights, 1200, isize, iline)
        if iy + needed + 8 <= 572:
            insight_block = text_block("insights", "body", Region(x=40, y=iy, w=1200, h=needed), insights,
                                       spec="card_body", size=isize, line=iline, editable=True)
    s0 = panels[0][1]
    first, last = s0.months[0], s0.months[-1]
    blocks = [
        title_block("Search", sub_parts=[T("월별 검색 지수 — 자사 vs 경쟁사 ("), D(fmt_month_range(first, last)), T(")")]),
        lead, *blocks,
        *([insight_block] if insight_block else []),
        takeaway_block(P(T("월별 지수는 같은 요청·공통 스케일의 상대값", bold=True),
                         T(" — 브랜드별 최대값 정규화 없음, 결측 월은 선을 잇지 않음"), bullet="▶")),
        _footnote(ctx, fact_ids, [T("월별 지수 "), D(fmt_month_range(first, last)), T(" · 세트 공통 스케일(같은 요청) 상대 지수")]),
    ]
    return SlideSpec(slide_id="2-8b", template_id="search_trend.v1", page_role="content", section_id="search",
                     title="월별 검색 지수", blocks=_decorate(ctx, blocks),
                     finding_ids=[f.id for f in findings], needs_review=not findings, is_data=True)


# ---------------------------------------------------------------- 2-8c

def combo_share_pages(ctx: QuantContext) -> list[SlideSpec]:
    cfg = ctx.config
    cats = sorted({c for b in ctx.project.brands for c in ctx.metrics.cats(b.id, cfg.main_window, "all")})
    pages = []
    for cat in cats:  # one page per cat, name order; never mix cats (PRD 11)
        tables = [(b, ctx.metrics.find_share(b.id, cfg.main_window, "all", cat)) for b in ctx.project.brands]
        tables = [(b, t) for b, t in tables if t is not None][:3]
        if not tables:
            continue
        shown = {b.id: set(t.entities) for b, t in tables}
        findings = _pick_findings(ctx, [b.id for b, _ in tables], {"RULE-R05"}, shown, {cfg.main_window}, cat=cat)
        finding = findings[0] if findings else None
        xs, w = _panel_xs(len(tables))
        n_items = max(len(t.entities) for _, t in tables)
        row_h, label_pt = _bar_metrics(len(tables), n_items)
        chart_h = n_items * row_h + 16
        total = 36 + 12 + chart_h + 6 + 44
        top = _vstack_top(total)
        blocks: list[Block] = []
        fact_ids: list[str] = []
        for i, ((brand, table), x) in enumerate(zip(tables, xs)):
            r05 = next((f for f in ctx.findings if f.rule_id == "RULE-R05" and f.brand_id == brand.id and f.cat == cat), None)
            key = r05.rival if r05 else None
            blocks += _panel_header(f"panel{i}_header", x, top, w, [N(brand.name), T(" 세트 · +"), N(cat), T(" 조합어 (%)")])
            items = [BarItem(entity=e, label=f"{e}+{cat}", fact_id=table.shares[e].id,
                             display=ctx.pf.fact(table.shares[e], "share").display, value=_bar_value(table.share(e)),
                             role="self" if e == brand.name else ("key" if e == key else "other"))
                     for e in table.ordered()]
            blocks.append(BarChartBlock(block_id=f"panel{i}_chart", region=Region(x=x, y=top + 48, w=w, h=chart_h), items=items,
                                    label_size=label_pt))
            fact_ids += [it.fact_id for it in items]
            caption = []
            name = ctx.metrics.find_share(brand.id, cfg.main_window, "all")
            if name:
                caption.append(P(T("브랜드명 검색("), M(cfg.main_window, "window"), T(") "), N(brand.name), T(" "),
                                 ctx.pf.fact(name.shares[brand.name], "share", bold=False), T(" · "),
                                 ctx.pf.fact(name.ranks[brand.name], "rank", bold=False)))
                fact_ids += [name.shares[brand.name].id, name.ranks[brand.name].id]
            blocks.append(text_block(f"panel{i}_caption", "caption", Region(x=x, y=top + 48 + chart_h + 6, w=w, h=44),
                                     caption, spec="caption", align="c"))
        def _combo_parts(f: Finding, *, emphasize: bool = True) -> list:
            s = f.summary
            t = ctx.metrics.find_share(f.brand_id, cfg.main_window, "all", cat)
            me = ctx.brand_name(f.brand_id)
            return [T("+"), N(cat), T(" 조합어 검색은 "), N(s["rival"]), T(" "), ctx.pf.fact(t.shares[s["rival"]], "share"),
                    T(" 우위, "), N(me), T(" "), ctx.pf.fact(t.shares[me], "share"), T(" — "),
                    T("브랜드명 대비 카테고리 탐색 열세", bold=emphasize)]

        if finding:
            lead = _neutral_lead(*_combo_parts(finding))
        else:
            lead = _neutral_lead(T("+"), N(cat), T(" 조합어 검색 세트 안의 브랜드별 점유"))
        insights = [Paragraph(parts=_combo_parts(f, emphasize=False), bullet=circled(i)) for i, f in enumerate(findings)]
        for f in findings:
            fact_ids += list(f.fact_ids)
        insight_block = None
        if insights:
            isize, iline = 11.5, 17.0
            iy = top + total + 10
            needed = height_at(insights, 1200, isize, iline)
            if iy + needed + 8 <= 572:
                insight_block = text_block("insights", "body", Region(x=40, y=iy, w=1200, h=needed), insights,
                                           spec="card_body", size=isize, line=iline, editable=True)
        t0 = tables[0][1]
        blocks = [
            title_block("Search", sub_parts=[T("카테고리 조합어 검색 점유 — +"), N(cat), T(" ("), M(cfg.main_window, "window"), T(")")]),
            lead, *blocks,
            *([insight_block] if insight_block else []),
            takeaway_block(P(T("조합어 점유는 '브랜드+카테고리' 검색어 세트 내부 비중", bold=True),
                             T(" — 브랜드명 검색(이름으로 찾는 수요)과 별도 세트로 계산"), bullet="▶")),
            _footnote(ctx, fact_ids, [M(cfg.main_window, "window"), T(" "), PERIOD(t0.period_start, t0.period_end)],
                      [T("조합어 세트 내 지수 합 비율(상대지수)")]),
        ]
        pages.append(SlideSpec(slide_id=f"2-8c-{cat}", template_id="combo_share.v1", page_role="content",
                               section_id="search", title=f"+{cat} 조합어 검색 점유", blocks=_decorate(ctx, blocks),
                               finding_ids=[f.id for f in findings], needs_review=not findings, is_data=True))
    return pages


# ---------------------------------------------------------------- 2-8d

def target_table(ctx: QuantContext) -> Optional[SlideSpec]:
    cfg = ctx.config
    reg = ctx.metrics.registry
    columns = [
        TableColumn(key="brand", label="브랜드", width=0.10),
        TableColumn(key="kw", label="검색어", width=0.14),
        TableColumn(key="all", label=f"전체 {cfg.main_window} (순위)", width=0.16),
        TableColumn(key="t", label=f"키 타겟 {cfg.main_window} (순위)", width=0.21),
        TableColumn(key="diff", label="차이", width=0.11),
        TableColumn(key="lead", label="키 타겟 1위", width=0.28),
    ]
    rows: list[TableRow] = []
    fact_ids: list[str] = []
    brands_used = []
    missing: list[str] = []
    for b in ctx.project.brands:
        pairs = []
        for cat in [None, *ctx.metrics.cats(b.id, cfg.main_window, "all")]:
            a = ctx.metrics.find_share(b.id, cfg.main_window, "all", cat)
            t = ctx.metrics.find_share(b.id, cfg.main_window, "T", cat)
            if a and t and a.entities == t.entities:
                pairs.append((cat, a, t))
            elif cat is None:
                missing.append(b.name)
        if not pairs or pairs[0][0] is not None:
            continue  # brand-name row is required for the group
        brands_used.append(b)
        target_label = b.target.label if b.target else "키 타겟"
        for j, (cat, a, t) in enumerate(pairs):
            me = b.name
            diff = reg.derive("diff", [t.shares[me].id, a.shares[me].id], brand_id=b.id, entity=me,
                              metric="target_share_diff", value=t.share(me) - a.share(me), unit="pp",
                              params={"window": cfg.main_window, "from": "all", "to": "T"})
            leader = t.ordered()[0]
            highlight = cat is None
            rows.append(TableRow(cells=[
                TableCell(paragraphs=[P(N(b.name))], merge_down=len(pairs) - 1 if j == 0 else 0, merged=j > 0),
                TableCell(paragraphs=[P(T("브랜드명"))] if cat is None else [P(T("+"), N(cat))]),
                TableCell(paragraphs=[P(ctx.pf.fact(a.shares[me], "share", bold=False), T(" ("),
                                        ctx.pf.fact(a.ranks[me], "rank_num", bold=False), T(")"))]),
                TableCell(paragraphs=[P(M(_short_target(target_label), "target_label", bold=highlight), T(" "),
                                        ctx.pf.fact(t.shares[me], "share", bold=highlight), T(" (", bold=highlight),
                                        ctx.pf.fact(t.ranks[me], "rank_num", bold=highlight), T(")", bold=highlight))],
                          fill="highlight" if highlight else None),
                TableCell(paragraphs=[P(ctx.pf.fact(diff, "pp", bold=False))]),
                TableCell(paragraphs=[P(N(leader), T(" "), ctx.pf.fact(t.shares[leader], "share", bold=False))]),
            ], ref=f"{b.id}:{cat or 'name'}"))
            fact_ids += [a.shares[me].id, a.ranks[me].id, t.shares[me].id, t.ranks[me].id, diff.id, t.shares[leader].id]
    if not rows:
        return None
    shown = {b.id: {b.name} for b in brands_used}
    findings = _pick_findings(ctx, [b.id for b in brands_used], {"RULE-R06"}, shown,
                              {f"{cfg.main_window}:all", f"{cfg.main_window}:T"})
    finding = findings[0] if findings else None
    row_h, head_h = 36, 32
    table_h = head_h + row_h * len(rows)
    table_top = _vstack_top(table_h)
    table = TableBlock(block_id="table", region=Region(x=60, y=table_top, w=1160, h=table_h), columns=columns,
                       rows=rows, row_height=row_h, header_height=head_h, size=10, header_size=10)

    def _target_parts(f: Finding, *, emphasize: bool = True) -> list:
        s = f.summary
        b = ctx.project.brand(f.brand_id)
        all_t = ctx.metrics.find_share(b.id, cfg.main_window, "all")
        tgt = ctx.metrics.find_share(b.id, cfg.main_window, "T")
        return [M(b.target.label if b.target else "키 타겟", "target_label"), T(" 타겟에서 "), N(b.name), T(" "),
                T("상대 점유 하락", bold=emphasize), T(" — 전체 "), ctx.pf.fact(all_t.shares[b.name], "share"),
                T(" → 타겟 "), ctx.pf.fact(tgt.shares[b.name], "share")]

    if finding:
        lead = _neutral_lead(*_target_parts(finding))
    else:
        lead = _neutral_lead(T("전체 대비 키 타겟 검색 점유 비교"))
    insights = [Paragraph(parts=_target_parts(f, emphasize=False), bullet=circled(i)) for i, f in enumerate(findings)]
    for f in findings:
        fact_ids += list(f.fact_ids)
    insight_block = None
    if insights:
        isize, iline = 11.5, 17.0
        iy = table_top + table_h + 10
        needed = height_at(insights, 1160, isize, iline)
        if iy + needed + 8 <= 572:
            insight_block = text_block("insights", "body", Region(x=60, y=iy, w=1160, h=needed), insights,
                                       spec="card_body", size=isize, line=iline, editable=True)
    b0 = brands_used[0]
    a0 = ctx.metrics.find_share(b0.id, cfg.main_window, "all")
    target_defs = " · ".join(f"{b.name} 키 타겟={b.target.label}" for b in brands_used if b.target)
    blocks = [
        title_block("Search", "키 타겟 연령·성별 검색 점유 비교"),
        lead, table,
        *([insight_block] if insight_block else []),
        takeaway_block(P(T("타겟 점유는 같은 검색어 세트에 연령·성별 필터를 적용한 세트 내부 비중", bold=True),
                         T(" — 전체·타겟은 각자 요청 단위 공통 스케일"), bullet="▶")),
        _footnote(ctx, fact_ids, [M(cfg.main_window, "window"), T(" "), PERIOD(a0.period_start, a0.period_end)],
                  [M(target_defs, "target_label")] if target_defs else []),
    ]
    return SlideSpec(slide_id="2-8d", template_id="target_table.v1", page_role="content", section_id="search",
                     title="키 타겟 검색 점유", blocks=_decorate(ctx, blocks),
                     finding_ids=[f.id for f in findings], needs_review=not findings, is_data=True)


def _short_target(label: str) -> str:
    return label.split("·")[0].strip()


# ---------------------------------------------------------------- 3-1

CHANNEL_SHORT = {"youtube": "YT", "instagram": "IG"}


def creator_pages(ctx: QuantContext, brand_id: str) -> list[SlideSpec]:
    brand = ctx.project.brand(brand_id)
    window = ctx.project.window_for("influencer")
    start, end = (window.start, window.end) if window else (ctx.project.period.start, ctx.project.period.end)
    pms = [pm for pm in ctx.metrics.posts.get(brand_id, [])
           if pm.post.owner_type == "creator" and start <= pm.post.posted_at <= end]
    if not pms:
        return []
    pms.sort(key=lambda pm: (pm.post.quarter(), pm.post.posted_at, pm.post.post_id))
    asset = ctx.influencer_assets.get(brand_id)
    with_image = asset is not None

    table_x, table_w = (520, 712) if with_image else (48, 1184)
    head_h, row_h = 28, 26
    label_h = 30
    avail = region("body").h - label_h - 10
    per_page = min(12, int((avail - head_h) // row_h))
    pages_n = math.ceil(len(pms) / per_page)
    size = math.ceil(len(pms) / pages_n)
    chunks = [pms[i:i + size] for i in range(0, len(pms), size)]

    ad = ctx.metrics.ad.get(brand_id)
    finding = None
    finding_rule = None
    # 3-1 accepts RULE-R10 and RULE-R11 (04_지표정의_발견규칙.md 섹션 C); only one leads, so
    # the stronger wins. R11 cites two representative posts that must land on this same page,
    # so it only competes when the table isn't split across pages.
    candidates = [f for f in ctx.findings if f.rule_id in ("RULE-R10", "RULE-R11") and f.brand_id == brand_id
                 and f.id not in ctx.used_leads]
    if len(chunks) > 1:
        candidates = [f for f in candidates if f.rule_id != "RULE-R11"]
    if candidates:
        finding = max(candidates, key=lambda f: f.strength)
        finding_rule = finding.rule_id
        ctx.used_leads.add(finding.id)

    slides = []
    # Collected posts carry no product name; an all-dash column says nothing, so show the post date instead.
    has_product = any(pm.post.product for pm in pms)
    for page_i, chunk in enumerate(chunks):
        rows: list[TableRow] = []
        fact_ids: list[str] = []
        for pm in chunk:
            rows.append(_creator_row(ctx, pm, fact_ids, has_product))
        columns = [
            TableColumn(key="qc", label="분기·채널", width=0.12),
            TableColumn(key="creator", label="크리에이터 (규모)", width=0.38 if not with_image else 0.36),
            TableColumn(key="product", label="제품", width=0.18) if has_product else TableColumn(key="posted", label="게시일", width=0.18),
            TableColumn(key="views", label="조회", width=0.16),
            TableColumn(key="er", label="반응률", width=0.16 if not with_image else 0.18),
        ]
        page_row_h = min(34.0, max(row_h, (avail - head_h) / max(len(rows), 1)))
        table_h = head_h + page_row_h * len(rows)
        top = region("body").y
        label_reg = Region(x=table_x, y=top, w=table_w, h=label_h)
        blocks: list[Block] = [
            ShapeBlock(block_id="table_label_bg", region=label_reg, fill="navy"),
            text_block("table_label", "panel_header", label_reg,
                       [P(PERIOD(start, end), T(" 크리에이터 게시물 (분기순)"))], spec="panel_header", align="c",
                       valign="m", color="white", bold=True),
            TableBlock(block_id="table", region=Region(x=table_x, y=top + label_h + 10, w=table_w, h=table_h), columns=columns,
                       rows=rows, row_height=page_row_h, header_height=head_h, size=10 if page_row_h > 30 else 9.5,
                       header_size=10 if page_row_h > 30 else 9.5),
        ]
        if with_image and page_i == 0:
            blocks += _reference_panel(asset)
        takeaway = None
        if page_i == 0 and ad and ad.ad_view_share is not None:
            parts = [T("광고 추정 후보 조회 비중 "), ctx.pf.fact(ad.ad_view_share, "share"), T(" · 분류 가능 조회 비중 "),
                     ctx.pf.fact(ad.coverage, "share", bold=False), T(" — 조회 있는 creator 게시물 "),
                     ctx.pf.fact(ad.view_eligible_posts, "posts", bold=False), T(" 기준, 광고 집행·유료 조회의 증거 아님")]
            takeaway = takeaway_block(P(*parts, bullet="▶"))
            fact_ids += [ad.ad_view_share.id, ad.coverage.id, ad.view_eligible_posts.id]
        if page_i == 0 and finding_rule == "RULE-R10":
            lead = _neutral_lead(T("관측 조회가 "), T("광고 추정 후보 게시물에 집중", bold=True), T(" — 조회 있는 creator 게시물 조회의 "),
                                 ctx.pf.fact(ad.ad_view_share, "share"))
        elif page_i == 0 and finding_rule == "RULE-R11":
            lead = _neutral_lead(T("반응률 상위 크리에이터는 "), T("팔로워 규모가 작음", bold=True), T(" — 반응률 상위 팔로워 "),
                                 ctx.pf.fact(finding.fact_ids[0], "lead_count"), T(" vs 조회 상위 "),
                                 ctx.pf.fact(finding.fact_ids[1], "lead_count"))
        elif page_i == 0:
            lead = _neutral_lead(N(brand.name), T(" 관련 크리에이터 게시물 관측 현황"))
        else:
            lead = _neutral_lead(N(brand.name), T(" 관련 크리에이터 게시물 상세 (계속)"))
        measured = max(pm.post.measured_at for pm in pms)
        foot = [T("*반응률=(좋아요+댓글)÷팔로워(YouTube는 구독자) · †좋아요 비공개: 댓글만 반영한 부분 반응률 · 광고 추정=좋아요÷조회 "),
                M(f"{ctx.config.ad_like_view_threshold}%", "config"), T(" 미만(휴리스틱) · 모든 지표 "), D(measured),
                T(" 관측값(게시 기간 내 발생량 아님) · " + " · ".join(_sources_for(ctx, fact_ids)))]
        title_suffix = [T(" ("), D(fmt_month_range(f"{start:%Y-%m}", f"{end:%Y-%m}")), T(")")]
        if len(chunks) > 1:
            title_suffix += [T(" "), M(f"{page_i + 1}/{len(chunks)}", "page")]
        all_blocks = [title_block("Influencer", sub_parts=[N(brand.name), T(" 크리에이터")] + title_suffix), lead, *blocks]
        if takeaway:
            all_blocks.append(takeaway)
        all_blocks.append(footnote_block([P(*foot)]))
        slide_id = f"3-1-{brand_id}" + (f"-p{page_i + 1}" if page_i else "")
        slides.append(SlideSpec(slide_id=slide_id, template_id="creator_table.v1" if not with_image else "creator_image_table.v1",
                                page_role="content", section_id="influencer", brand_id=brand_id,
                                title=f"{brand.name} 크리에이터", blocks=_decorate(ctx, all_blocks),
                                finding_ids=[finding.id] if (finding and page_i == 0) else [],
                                asset_ids=[asset.id] if (with_image and page_i == 0) else [],
                                parent_slide_id=f"3-1-{brand_id}" if page_i else None,
                                needs_review=page_i == 0 and finding is None, is_data=True))
    return slides


def _creator_row(ctx: QuantContext, pm: PostMetrics, fact_ids: list[str], has_product: bool = True) -> TableRow:
    post = pm.post
    is_ad = pm.ad_heuristic.value is True
    creator = [N(post.creator)]
    if post.followers is not None:
        creator += [T(" ("), ctx.pf.fact(post.fact_ids["followers"], "lead_count", bold=False), T(")")]
        fact_ids.append(post.fact_ids["followers"])
    if is_ad:
        creator += [T(" · 광고 추정 후보")]
    views = [ctx.pf.fact(post.fact_ids["views"], "int", bold=False)] if post.views is not None else [T("—")]
    if post.views is not None:
        fact_ids.append(post.fact_ids["views"])
    er = [ctx.pf.fact(pm.er, "er", bold=False)] if pm.er else [T("—")]
    if pm.er:
        fact_ids.append(pm.er.id)
    return TableRow(cells=[
        TableCell(paragraphs=[P(M(f"{post.quarter()} · {CHANNEL_SHORT[post.channel]}", "quarter"))]),
        TableCell(paragraphs=[P(*creator)]),
        TableCell(paragraphs=[P(N(post.product) if post.product else T("—"))] if has_product
                  else [P(D(post.posted_at) if post.posted_at else T("—"))]),
        TableCell(paragraphs=[P(*views)]),
        TableCell(paragraphs=[P(*er)]),
    ], muted=is_ad, ref=post.post_id)


def _reference_panel(asset: AssetRef) -> list[Block]:
    frame = Region(x=60, y=region("body").y + 40, w=430, h=356)
    label = Region(x=frame.x + 140, y=frame.y - 14, w=150, h=28)
    img = Region(x=frame.x + 20, y=frame.y + 28, w=390, h=230)
    return [
        ShapeBlock(block_id="ref_frame", region=frame, line="panel_border", fill="white"),
        ShapeBlock(block_id="ref_label_bg", region=label, fill="card_label"),
        text_block("ref_label", "panel_header", label, [P(T("레퍼런스"))], spec="card_label", align="c", valign="m"),
        ImageBlock(block_id="ref_image", region=img, asset_id=asset.id, crop=asset.crop),
        text_block("ref_caption", "caption", Region(x=frame.x + 20, y=img.y + img.h + 10, w=390, h=50),
                   [P(N(asset.title), bullet="▲", color="link")] + ([P(T(asset.description))] if asset.description else []),
                   spec="caption", align="c"),
    ]


# ---------------------------------------------------------------- 5 recap

PILLARS = [
    ("검색 경쟁", {"RULE-R03", "RULE-R04", "RULE-R05"}),
    ("타겟 적합성", {"RULE-R06"}),
    # R13은 04_지표정의_발견규칙.md 섹션 C가 Recap 후보로 직접 지정; R12는 같은 콘텐츠·
    # 관측 도메인이라 묶었다(3-1은 R10/R11로 리드 자리가 이미 다 차 있어 넣을 자리가 없음).
    ("콘텐츠·관측 성과", {"RULE-R10", "RULE-R12", "RULE-R13"}),
]


def recap(ctx: QuantContext) -> Optional[SlideSpec]:
    multi = len(ctx.project.brands) > 1
    pillars = []
    for name, rules in PILLARS:
        items = [f for f in ctx.findings if f.rule_id in rules][:2]
        if items:
            pillars.append((name, items))
    if not pillars:
        return None
    n = len(pillars)
    w = {1: 520, 2: 460, 3: 358}[n]
    gap = 42
    total = n * w + (n - 1) * gap
    x0 = 640 - total / 2
    blocks: list[Block] = [title_block("Recap")]
    fact_ids: list[str] = []
    finding_ids: list[str] = []
    for i, (name, items) in enumerate(pillars):
        x = x0 + i * (w + gap)
        head = Region(x=x, y=300, w=w, h=84)
        body = Region(x=x, y=396, w=w, h=150)
        blocks.append(ShapeBlock(block_id=f"pillar{i}_head_bg", region=head, fill="navy"))
        blocks.append(text_block(f"pillar{i}_head", "panel_header", head, [P(M(f"{i + 1})", "item_no"), T(f" {name}"))], spec="pillar_header",
                                 align="c", valign="m", color="white", bold=True))
        blocks.append(ShapeBlock(block_id=f"pillar{i}_body_bg", region=body, fill="pillar_body"))
        paras = []
        for k, f in enumerate(items):
            head, value = _recap_item(ctx, f)
            if multi:
                head = [N(ctx.brand_name(f.brand_id), bold=True), T(" ")] + head
            first = P(*head)
            first.space_before = 10 if k else 0
            paras += [first, P(*value)]
            fact_ids += [p.fact_id for p in head + value if p.fact_id]
            finding_ids.append(f.id)
        inner = Region(x=x + 18, y=body.y + 12, w=w - 36, h=body.h - 24)
        blocks.append(text_block(f"pillar{i}_body", "body", inner, paras, spec="pillar_body", align="c", valign="m"))
    blocks.append(_footnote(ctx, fact_ids, [T("본문 장표 근거 요약")]))
    return SlideSpec(slide_id="5-recap", template_id="recap.v1", page_role="recap", section_id="recap", title="Recap",
                     blocks=_decorate(ctx, blocks), finding_ids=finding_ids, is_data=False)


def _recap_item(ctx: QuantContext, f: Finding) -> tuple[list, list]:
    """(label line, numeric line): numbers sit on their own line so they never wrap mid-token."""
    s = f.summary
    pf = ctx.pf
    if f.rule_id == "RULE-R04":
        return ([N(s["rival"]), T(" 대비 브랜드명 점유 우위 축소")],
                [M(ctx.config.long_window, "window"), T(" "), pf.fact(f.fact_ids[0], "gap"), T(" → "),
                 M(ctx.config.main_window, "window"), T(" "), pf.fact(f.fact_ids[1], "gap")])
    if f.rule_id == "RULE-R03":
        return ([N(s["rival"]), T(" 월별 검색 지수 우위 지속")],
                [D(fmt_month_range(s["start_month"], s["end_month"])), T(" · "), pf.fact(f.fact_ids[0], "months")])
    if f.rule_id == "RULE-R05":
        return ([T("+"), N(s["cat"]), T(" 조합어 "), N(s["rival"]), T(" 우위")],
                [N(s["rival"]), T(" "), pf.fact(f.fact_ids[1], "share"), T(" vs "), N(ctx.brand_name(f.brand_id)), T(" "),
                 pf.fact(f.fact_ids[0], "share")])
    if f.rule_id == "RULE-R06":
        b = ctx.project.brand(f.brand_id)
        return ([M(_short_target(b.target.label) if b.target else "키 타겟", "target_label"), T(" 타겟 상대 점유 하락")],
                [T("타겟 "), pf.fact(f.fact_ids[1], "share"), T(" · 전체 대비 "), pf.fact(f.fact_ids[2], "pp")])
    if f.rule_id == "RULE-R10":
        return ([T("광고 추정 후보 게시물에 관측 조회 집중")], [T("조회 있는 creator 게시물 조회의 "), pf.fact(f.fact_ids[0], "share")])
    if f.rule_id == "RULE-R12":
        return ([T("공동 게시물 반응 저하")], [T("크리에이터 평소 게시물의 "), pf.fact(f.fact_ids[0], "times")])
    if f.rule_id == "RULE-R13":
        start, end = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
        return ([T("자체 채널 운영 공백")], [D(start), T(" ~ "), D(end), T(" · "), pf.fact(f.fact_ids[0], "days")])
    return ([T(f.allowed_expression)], [])
