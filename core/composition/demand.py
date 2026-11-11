"""수요·소비자 차트 장 (P3-3): VC1 커뮤니티별 부정률 + 원문 카드, PP1 페인 포인트, SH1 품목별 쇼핑 수요·성수기.

모두 자사 브랜드 하나의 장이다(원칙 8). 숫자는 확인된 Fact 또는 채택 자료에서 계산한 파생값(P1-2)만 쓰고,
자료가 모자라면 장을 만들지 않는다(P3-6 규칙: 원문 20건 미만, 선 차트 점 4개 미만 등).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from core.composition.cases import _fit_lines, _publisher
from core.composition.chrome import D, M, N, P, T, insight_blocks, lead_block, text_block, title_block
from core.composition.compare import (
    bar_item, facts_of, fit_bars, footnote, sample_note, single_brand, text,
)
from core.composition.formatters import fmt_month_label
from core.composition.quant import QuantContext, _decorate, _panel_header
from core.composition.tokens import region
from core.ingestion.shopping_index import AGE_LABEL
from core.metrics.derived import site_of
from core.schemas.materials import CaseMaterial
from core.schemas.slidespec import (
    BarChartBlock, BarSeries, Block, LineChartBlock, LinePoint, LineSeries, Part, Region, ShapeBlock, SlideSpec,
)

SENTIMENT_TAG = {"negative": ("부정", "red"), "positive": ("긍정", "navy"), "neutral": ("중립", "muted")}


# ---------------------------------------------------------------- 인용 카드 (VC1·PP1 공용)

def _quote_text(m: CaseMaterial) -> str:
    """The card shows words from the source itself: an accepted verbatim excerpt, else the post's own title."""
    quote = next((c.quote for c in m.claims if c.quote and c.review_status == "accepted"), None)
    return quote or next((c.quote for c in m.claims if c.quote), None) or m.title


def quote_cards(materials: list[CaseMaterial], x: float, y: float, w: float, h: float,
                prefix: str = "quote") -> list[Block]:
    """Up to 4 stacked cards in the box: sentiment tag, the verbatim words (2~3 lines), outlet + date."""
    if not materials:
        return []
    gap = 10.0
    card_h = min(118.0, (h - gap * (len(materials) - 1)) / len(materials))
    lines = 3 if card_h >= 100 else 2
    out: list[Block] = []
    for i, m in enumerate(materials):
        cy = y + i * (card_h + gap)
        tag, color = SENTIMENT_TAG.get(m.voc_sentiment or "", ("원문", "muted"))
        src: list[Part] = [N(_publisher(m))]
        when = m.source.published_at or m.activity_date
        if when:
            src += [T(" · "), D(when)]
        out += [
            ShapeBlock(block_id=f"{prefix}{i}_bg", region=Region(x=x, y=cy, w=w, h=card_h), fill="tint"),
            ShapeBlock(block_id=f"{prefix}{i}_bar", region=Region(x=x, y=cy, w=4, h=card_h), fill=color),
            text(f"{prefix}{i}_tag", Region(x=x + 14, y=cy + 6, w=60, h=18), [T(tag)], color=color, weight="bold",
                 size=9),
            text_block(f"{prefix}{i}", "body", Region(x=x + 14, y=cy + 24, w=w - 26, h=card_h - 46),
                       [P(Part(type="quote", text=_fit_lines(f"“{_quote_text(m)}”", w - 26, 10, lines)))],
                       spec="card_body", size=10, line=15),
            text(f"{prefix}{i}_src", Region(x=x + 14, y=cy + card_h - 22, w=w - 26, h=18), src, color="muted", size=8.5),
        ]
    return out


def _voc_pool(materials: list[CaseMaterial], self_name: str) -> list[CaseMaterial]:
    return [m for m in materials if m.section_id == "voc" and m.review_status == "accepted" and not m.voc_sponsored
            and m.voc_sentiment and m.entity == self_name]


def _pick_quotes(pool: list[CaseMaterial], k: int = 4) -> list[CaseMaterial]:
    """Negatives first (the page is about complaints), then a positive and neutral for balance; newest first."""
    def newest(ms):
        return sorted(ms, key=lambda m: (str(m.source.published_at or m.activity_date or ""), m.id), reverse=True)
    neg = newest([m for m in pool if m.voc_sentiment == "negative"])
    pos = newest([m for m in pool if m.voc_sentiment == "positive"])
    neu = newest([m for m in pool if m.voc_sentiment == "neutral"])
    picked = neg[:2] + pos[:1] + neu[:1]
    rest = [m for m in neg[2:] + pos[1:] + neu[1:] if m not in picked]
    return (picked + rest)[:k]


# ---------------------------------------------------------------- VC1 커뮤니티별 부정률 + 원문 카드

VC_MIN_SITES = 1  # '전체' 말고 출처가 하나 이상(파생 Fact는 이미 원문 20건 이상일 때만 생긴다)


def voc_negative_page(ctx: QuantContext, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    brand = single_brand(ctx)
    if brand is None:
        return None
    facts = {f.dims.get("site"): f for f in reversed(facts_of(ctx, "voc_negative_rate", brand.id)) if f.entity == brand.name}
    total = facts.pop("전체", None)
    sites = sorted(facts.items(), key=lambda kv: (-int(kv[1].dims.get("n", 0)), kv[0]))[:7]
    if total is None or len(sites) < VC_MIN_SITES:
        return None
    body = region("body")
    chart_w = body.w * 0.56
    top_site = max(sites, key=lambda kv: kv[1].value)[0]
    items = [bar_item(ctx, brand.name, "전체", total, "share", "self")]
    items += [bar_item(ctx, brand.name, site, f, "share", "key" if site == top_site and len(sites) > 1 else "other")
              for site, f in sites]
    blocks: list[Block] = _panel_header("chart_header", body.x, body.y, chart_w, [T("커뮤니티별 부정 비율(%)")])
    chart = BarChartBlock(block_id="chart", region=fit_bars(Region(x=body.x, y=body.y + 44, w=chart_w, h=body.h - 44),
                                                             len(items)),
                          items=items, number_format='0.0"%"', unit="percent", label_size=10.5, gap_width=60)
    blocks.append(chart)
    fact_ids = [it.fact_id for it in chart.bar_items()]
    pool = _voc_pool(materials, brand.name)
    picked = _pick_quotes(pool)
    qx = body.x + chart_w + 32
    qw = body.w - chart_w - 32
    if picked:
        blocks += _panel_header("quote_header", qx, body.y, qw, [T("대표 원문")])
        blocks += quote_cards(picked, qx, body.y + 44, qw, body.h - 44)
    hi_site, hi = max(sites, key=lambda kv: kv[1].value)
    lo_site, lo = min(sites, key=lambda kv: kv[1].value)
    insights = [([T("전체 부정 비율")], [N(brand.name), T(" 원문 "), ctx.pf.fact(total, "share", bold=True)])]
    if len(sites) > 1:
        insights.append(([T("가장 높은 곳")], [N(hi_site), T(" "), ctx.pf.fact(hi, "share", bold=True)]))
        insights.append(([T("가장 낮은 곳")], [N(lo_site), T(" "), ctx.pf.fact(lo, "share", bold=False)]))
    for _, parts in insights:
        fact_ids += [p.fact_id for p in parts if p.type == "fact"]
    lead = lead_block([P(N(brand.name), T(" 소비자 원문 — 커뮤니티별 부정 비율과 대표 원문"))])
    blocks = [
        title_block("Customer", "커뮤니티별 부정 비율"), lead, *blocks, *insight_blocks(insights),
        footnote(ctx, fact_ids, [T("채택한 소비자 원문(협찬·체험단 제외)")], sample_note([total, *facts.values()], "원문")),
    ]
    return SlideSpec(slide_id="VC1", template_id="voc_negative.v1", page_role="content", section_id="voc",
                     title="커뮤니티별 부정 비율", blocks=_decorate(ctx, blocks), source_ids=[m.source.id for m in picked],
                     needs_review=True, is_data=True)


# ---------------------------------------------------------------- PP1 페인 포인트

PP_MIN, PP_MAX = 3, 8


def _locator_materials(locator: Optional[str], pool: list[CaseMaterial]) -> list[CaseMaterial]:
    """Representative posts named in a pain-point fact's source_locator (material ids or URLs)."""
    if not locator:
        return []
    by_key = {m.id: m for m in pool}
    by_key.update({m.source.url: m for m in pool if m.source.url})
    out = []
    for token in locator.split(","):
        m = by_key.get(token.strip())
        if m and m not in out:
            out.append(m)
    return out


def pain_point_page(ctx: QuantContext, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    """PP1: 자사 원문에서 묶은 불만 표현 상위 5~8개 막대 + 오른쪽에 대표 원문(있을 때)."""
    brand = single_brand(ctx)
    if brand is None:
        return None
    newest: dict[str, object] = {}
    for f in facts_of(ctx, "pain_point_count", brand.id):
        if f.entity == brand.name and f.dims.get("pain_point"):
            newest.setdefault(f.dims["pain_point"], f)
    ranked = sorted(newest.items(), key=lambda kv: (-kv[1].value, kv[0]))[:PP_MAX]
    if len(ranked) < PP_MIN:
        return None
    pool = [m for m in materials if m.section_id == "voc" and m.review_status == "accepted" and m.entity == brand.name]
    reps: list[CaseMaterial] = []
    for _, f in ranked:
        for m in _locator_materials(f.source_locator, pool):
            if m not in reps:
                reps.append(m)
                break
        if len(reps) >= 3:
            break
    body = region("body")
    chart_w = body.w * (0.56 if reps else 1.0)
    items = [bar_item(ctx, brand.name, name, f, "count", "key" if i == 0 else "self") for i, (name, f) in enumerate(ranked)]
    blocks: list[Block] = _panel_header("chart_header", body.x, body.y, chart_w, [T("불만 표현별 원문 수")])
    chart = BarChartBlock(block_id="chart", region=fit_bars(Region(x=body.x, y=body.y + 44, w=chart_w, h=body.h - 44),
                                                             len(items)),
                          items=items, number_format='#,##0"건"', unit="count", label_size=10.5, gap_width=55)
    blocks.append(chart)
    fact_ids = [it.fact_id for it in chart.bar_items()]
    if reps:
        qx, qw = body.x + chart_w + 32, body.w - chart_w - 32
        blocks += _panel_header("quote_header", qx, body.y, qw, [T("대표 원문")])
        blocks += quote_cards(reps, qx, body.y + 44, qw, body.h - 44)
    insights = []
    for i, (name, f) in enumerate(ranked[:3]):
        insights.append(([M(f"{i + 1}위", "rank"), T(" "), N(name)], [T("원문 "), ctx.pf.fact(f, "count", bold=True),
                                                                      T("건에서 언급")]))
        fact_ids.append(f.id)
    lead = lead_block([P(N(brand.name), T(" 소비자가 자주 말한 불편 — 비슷한 표현을 묶어 원문 수로"))])
    blocks = [
        title_block("Customer", "페인 포인트"), lead, *blocks, *insight_blocks(insights),
        footnote(ctx, fact_ids, [T("채택한 원문·댓글의 불만 표현을 AI가 비슷한 것끼리 묶어 셈")],
                 sample_note([f for _, f in ranked], "원문")),
    ]
    return SlideSpec(slide_id="PP1", template_id="pain_points.v1", page_role="content", section_id="voc",
                     title="페인 포인트", blocks=_decorate(ctx, blocks), source_ids=[m.source.id for m in reps],
                     needs_review=True, is_data=True)


# ---------------------------------------------------------------- SH1 품목별 쇼핑 수요·성수기

SH_MIN_POINTS = 4  # 선 차트는 점 4개 이상(P3-6)
SH_MAX_KEYWORDS = 5
LINE_ROLES = ["self", "key", "other", "other2", "other"]
AGE_ORDER = list(AGE_LABEL)


def shopping_demand_page(ctx: QuantContext) -> Optional[SlideSpec]:
    """SH1: 제품군별 월별 쇼핑 클릭 지수(같은 요청 = 같은 스케일인 묶음 하나) + 성수기 달 + 연령대별 클릭 비중."""
    brand = single_brand(ctx)
    if brand is None:
        return None
    by_scale: dict[str, dict[str, dict[str, object]]] = defaultdict(lambda: defaultdict(dict))
    for f in facts_of(ctx, "shop_click_index", brand.id):
        if "month" in f.dims:
            by_scale[f.dims.get("scale_id", "")][f.entity].setdefault(f.dims["month"], f)
    scales = [(sid, {kw: pts for kw, pts in kws.items() if len(pts) >= SH_MIN_POINTS}) for sid, kws in by_scale.items()]
    scales = [(sid, kws) for sid, kws in scales if kws]
    if not scales:
        return None
    order = {c: i for i, c in enumerate(brand.categories)}
    sid, kws = max(scales, key=lambda s: (len(s[1]), s[0]))
    keywords = sorted(kws, key=lambda k: (order.get(k, len(order)), k))[:SH_MAX_KEYWORDS]
    months = sorted({m for k in keywords for m in kws[k]})
    series = [LineSeries(entity=k, role=LINE_ROLES[i], points=[
        LinePoint(month=m, fact_id=kws[k][m].id, value=float(kws[k][m].value)) if m in kws[k] else LinePoint(month=m)
        for m in months]) for i, k in enumerate(keywords)]
    body = region("body")
    left_w = body.w * 0.62
    blocks: list[Block] = _panel_header("line_header", body.x, body.y, left_w, [T("제품군별 월별 쇼핑 클릭 지수")])
    chart_h = body.h - 44 - 64
    blocks.append(LineChartBlock(block_id="line", region=Region(x=body.x, y=body.y + 44, w=left_w, h=chart_h),
                                 categories=[fmt_month_label(m) for m in months], series=series))
    fact_ids = [p.fact_id for s in series for p in s.points if p.fact_id]
    # 성수기 띠: 제품군마다 평균 대비 기준 이상인 달(최대 3개)을 한 줄로
    peaks: dict[str, list] = defaultdict(list)
    for f in facts_of(ctx, "shop_peak_lift", brand.id):
        if f.entity in keywords and "month" in f.dims and all(p.dims["month"] != f.dims["month"] for p in peaks[f.entity]):
            peaks[f.entity].append(f)
    band_y = body.y + 44 + chart_h + 4
    band_rows = [k for k in keywords if peaks[k]][:3]
    for i, k in enumerate(band_rows):
        top = sorted(peaks[k], key=lambda f: -f.value)[:3]
        parts: list[Part] = [N(k, bold=True), T(" 성수기  ")]
        for j, f in enumerate(sorted(top, key=lambda f: f.dims["month"])):
            parts += ([T(" · ")] if j else []) + [M(fmt_month_label(f.dims["month"]), "month"), T(" "),
                                                 ctx.pf.fact(f, "share", bold=False)]
            fact_ids.append(f.id)
        blocks.append(ShapeBlock(block_id=f"peak{i}_bg", region=Region(x=body.x, y=band_y + i * 20, w=left_w, h=18),
                                 fill="highlight"))
        blocks.append(text(f"peak{i}", Region(x=body.x + 8, y=band_y + i * 20, w=left_w - 16, h=18), parts, size=9))
    # 오른쪽: 연령대별 클릭 비중(제품군 최대 3개, 같은 연령 순서)
    ages: dict[str, dict[str, object]] = defaultdict(dict)
    for f in facts_of(ctx, "shop_click_share", brand.id, by="age"):
        if f.entity in keywords:
            ages[f.entity].setdefault(f.dims.get("group"), f)
    age_kws = [k for k in keywords if ages[k]][:3]
    rx, rw = body.x + left_w + 32, body.w - left_w - 32
    if age_kws:
        groups = [g for g in AGE_ORDER if any(g in ages[k] for k in age_kws)]
        blocks += _panel_header("age_header", rx, body.y, rw, [T("연령대별 클릭 비중(%)")])
        colors = ["navy", "red", "line_other"]
        age_series = [BarSeries(name=k, color=colors[i], items=[
            bar_item(ctx, k, AGE_LABEL[g], ages[k][g], "share") if g in ages[k] else None for g in groups])
            for i, k in enumerate(age_kws)]
        age_chart = BarChartBlock(block_id="age", region=Region(x=rx, y=body.y + 44, w=rw, h=body.h - 44),
                                  categories=[AGE_LABEL[g] for g in groups], series=age_series,
                                  number_format='0"%"', unit="percent", label_size=9, gap_width=60)
        blocks.append(age_chart)
        fact_ids += [it.fact_id for it in age_chart.bar_items()]
    insights = []
    for k in band_rows[:2]:
        f = max(peaks[k], key=lambda f: f.value)
        insights.append(([N(k), T(" 성수기")], [M(fmt_month_label(f.dims["month"]), "month"), T(" 클릭 지수가 "),
                                               M("12개월", "window"), T(" 평균의 "),
                                               ctx.pf.fact(f, "share", bold=True)]))
    if age_kws:
        k = age_kws[0]
        g, f = max(ages[k].items(), key=lambda kv: kv[1].value)
        insights.append(([N(k), T(" 클릭 연령")], [N(AGE_LABEL.get(g, g)), T(" 비중 "), ctx.pf.fact(f, "share", bold=True),
                                                 T("로 가장 큼")]))
    for _, parts in insights:
        fact_ids += [p.fact_id for p in parts if p.type == "fact"]
    lead = lead_block([P(N(brand.name), T(" 주력 제품군의 쇼핑 수요 — 월별 클릭 추이, 성수기, 클릭 연령대"))])
    blocks = [
        title_block("Market", "품목별 쇼핑 수요·성수기"), lead, *blocks, *insight_blocks(insights[:3]),
        footnote(ctx, fact_ids, [T("네이버 쇼핑 클릭 지수(가장 큰 달 = "), M("100", "index_peak"),
                                   T("인 상대값, 같은 요청끼리만 비교) · 성수기 = "),
                                   M("12개월", "window"), T(" 평균 대비 기준 이상인 달")]),
    ]
    return SlideSpec(slide_id="SH1", template_id="shopping_demand.v1", page_role="content", section_id="search_trend",
                     title="품목별 쇼핑 수요·성수기", blocks=_decorate(ctx, blocks), needs_review=True, is_data=True)
