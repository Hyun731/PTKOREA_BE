"""진단 템플릿 6종 (IMPROVEMENT_PLAN P5-2) — 진단 플래너(P5-1)가 쓴 브랜드 진단을 장표로 그린다.

| ID | 장 | 지향 덱 쪽 | 구성 |
|---|---|---|---|
| D1 | 진단 요약 | 6 | 5단 화살표 머리 + 단계별 큰 숫자 + 강점·이탈 구간 괄호, 하단에 강점·약점 |
| D2 | 강점·약점 증명 | 7~10 | 헤드라인 v2(주장 + 근거) + 왼쪽 차트 + 오른쪽 원문 카드(태그 칩) + 하단 인사이트 |
| D3 | 경쟁 구도 | 11, 24 | 가격 계층(공식몰 가격, 리뷰 수) 또는 리뷰 격차 막대 + 대표 이미지 |
| D4 | CDJ 시사점 | 17 | 단계 × (고객 접점, 인지 상태 칩, 인지 증대 활동) 표 |
| D5 | 활동 제안 | 18 | 소셜·인플루언서·콘텐츠 열 카드, 카드마다 CDJ 칩과 근거 한 줄 |
| D6 | 결론 | 57 | 자사 브랜드 × 끊긴 구간 × 3개 축 표 |

규칙: 숫자는 모두 Fact part(차트 값은 fact_id)로만 들어가고, 지금 레지스트리에 없거나 쓸 수 없는 id는 건너뛴다
(자료가 바뀌어 사라진 수치를 그리지 않는다). 그릴 것이 모자라면 장을 만들지 않는다(고객용 덱에 '자료 없음' 금지).
D1~D5는 자사 브랜드 하나만 다룬다. D6은 자사 브랜드를 나란히 두지만 순위·점수는 매기지 않는다(원칙 8).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Optional

from core.composition.cases import _fit_lines
from core.composition.chrome import (
    N, P, T, footnote_block, headline_blocks, insight_blocks, lead_block, text_block, title_block,
)
from core.composition.compare import COUNT_FORMAT, bar_value, footnote, sample_note, text, usable
from core.composition.demand import quote_cards
from core.composition.formatters import UNIT_FORMATTER, format_value
from core.composition.quant import QuantContext, _decorate, _panel_header
from core.composition.tokens import region
from core.metrics.derived import POLARITY_LABEL, TOPIC_LABEL
from core.schemas.diagnosis import KIND_LABEL, PILLARS, STAGES, Diagnosis, DiagnosisClaim
from core.schemas.facts import Fact
from core.schemas.materials import AssetRef, CaseMaterial
from core.schemas.slidespec import (
    BarChartBlock, BarItem, BarSeries, Block, ImageBlock, LineChartBlock, LinePoint, LineSeries, Paragraph, Part,
    Region, ShapeBlock, SlideSpec, TableBlock, TableCell, TableColumn, TableRow,
)

# Templates whose headline is the diagnosis itself: the build-time AI headline writer leaves them alone.
TEMPLATES = {"D1": "diagnosis_summary.v1", "D2": "diagnosis_claim.v1", "D3": "diagnosis_competition.v1",
             "D4": "diagnosis_cdj.v1", "D5": "diagnosis_actions.v1", "D6": "diagnosis_conclusion.v1"}
OWN_HEADLINE = set(TEMPLATES.values())
# Summary pages carry their own bottom cards (no AI page insights on top of them).
OWN_INSIGHTS = {TEMPLATES[k] for k in ("D1", "D4", "D5", "D6")}

# 지표 이름(장표·프롬프트 공용). 없으면 Fact.label, 그다음 metric 그대로.
METRIC_LABEL = {
    "search_share": "검색 점유", "share_gap": "검색 점유 격차", "target_share_diff": "타겟 검색 점유 차이",
    "search_group_sum": "검색 지수 합", "search_index_monthly": "월별 검색 지수", "engagement_rate": "참여율",
    "like_view_rate": "조회 대비 좋아요", "ad_view_share": "광고 추정 조회 비중", "gap_reduction": "격차 변화",
    "owned_followers": "공식 계정 팔로워", "owned_posts_monthly": "월 게시 수", "owned_videos_monthly": "월 업로드",
    "owned_uploads_monthly": "월 업로드",
    "owned_likes_median": "게시물당 좋아요(중앙값)", "owned_reactions_median": "게시물당 반응(중앙값)",
    "owned_comments_median": "게시물당 댓글(중앙값)", "owned_views_avg": "평균 조회수", "owned_views_median": "조회수(중앙값)",
    "mention_total": "언급량", "blog_type_share": "블로그 문서 유형 비중", "voc_negative_rate": "소비자 원문 부정 비율",
    "voc_topic_share": "원문 주제 비중", "voc_path_share": "인식 경로 비중", "comment_sentiment_rate": "댓글 감성 비율",
    "pain_point_count": "페인 포인트 원문 수", "review_count": "리뷰 수", "review_rating": "리뷰 평점",
    "shop_click_index": "쇼핑 클릭 지수", "shop_peak_lift": "성수기 상승폭", "shop_click_share": "쇼핑 클릭 비중",
    "market_size": "시장 규모", "market_cagr": "연평균 성장률", "macro_indicator": "거시 지표",
    "purchase_factor_share": "구매 결정 요인 비중", "creator_followers": "크리에이터 팔로워", "post_likes": "게시물 좋아요",
    "post_comments": "게시물 댓글", "post_views": "게시물 조회수", "views": "조회수", "likes": "좋아요",
    "comments": "댓글", "followers": "팔로워", "official_price": "공식몰 가격",
}
SKIP_DIMS = {"scale_id", "n", "quote", "period", "keyword_group", "post_id", "rate_basis", "keyword"}
DIM_LABEL = {"topic": TOPIC_LABEL, "polarity": POLARITY_LABEL}
NUMBER_FORMAT = {"share": '0.0"%"', "pct_given": '0.0"%"', "rate": '0.00"%"', "count": COUNT_FORMAT,
                 "int": COUNT_FORMAT, "index": "0.0", "rating": "0.00", "krw": "#,##0", "pp": '0.0"pp"'}


# ---------------------------------------------------------------- 수치 설명 (진단 플래너와 공용)

def metric_label(f) -> str:
    return METRIC_LABEL.get(f.metric) or getattr(f, "label", None) or f.metric


def formatter_for(f) -> str:
    """How a fact is written in a diagnosis sentence or chart label."""
    unit = (f.unit or "").lower()
    if unit == "percent":
        return "pct_given" if isinstance(f, Fact) and f.source not in ("derived", "synthetic_fixture") else "share"
    fmt = UNIT_FORMATTER.get(unit, "int")
    try:
        format_value(fmt, f.value)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return "int"
    return fmt


def fact_dims(f) -> dict[str, str]:
    """Readable dims of a fact (or a derived value's parameters), helper keys left out."""
    raw = f.dims if isinstance(f, Fact) else {k: v for k, v in (getattr(f, "parameters", None) or {}).items()
                                              if isinstance(v, str)}
    return {k: DIM_LABEL.get(k, {}).get(str(v), str(v)) for k, v in raw.items() if k not in SKIP_DIMS and v not in (None, "")}


def fact_month(f) -> Optional[str]:
    """Time position of a monthly value ('2026-03'), for time-series charts."""
    if isinstance(f, Fact):
        if f.dims.get("month"):
            return f.dims["month"]
        if (f.period_start.year, f.period_start.month) == (f.period_end.year, f.period_end.month):
            return f.period_end.strftime("%Y-%m")
    return None


# ---------------------------------------------------------------- 공통

def _facts(ctx: QuantContext, fact_ids) -> list:
    """Facts still in the registry and usable, in the given order, without repeats."""
    out, seen = [], set()
    for fid in fact_ids or []:
        f = ctx.metrics.registry.get(fid)
        if f is not None and fid not in seen and usable(f) and isinstance(f.value, (Decimal, int)):
            seen.add(fid)
            out.append(f)
    return out


def _known(ctx: QuantContext, paragraphs: list[Paragraph]) -> bool:
    return all(p.fact_id in ctx.metrics.registry and usable(ctx.metrics.registry.get(p.fact_id))
               for para in paragraphs for p in para.parts if p.type == "fact")


def _fresh(ctx: QuantContext, paragraphs: list[Paragraph], *, color: Optional[str] = None) -> list[Paragraph]:
    """Stored sentences keep fact references; numbers are re-formatted from the current values."""
    out = []
    for para in paragraphs:
        parts = []
        for p in para.parts:
            if p.type == "fact" and p.fact_id:
                fresh = ctx.pf.fact(p.fact_id, p.formatter or "int", bold=p.bold)
                parts.append(p.model_copy(update={"display": fresh.display}))
            else:
                parts.append(p.model_copy(update={"color": color}) if color and p.color == "accent" else p)
        out.append(para.model_copy(update={"parts": parts, "bullet": None}))
    return out


def _fit(reg: Region, n: int, legend: bool = False, per: float = 64.0) -> Region:
    """A bar chart's own box: up to `per` px a bar (diagnosis pages have room), vertically centered."""
    h = min(reg.h, per * max(n, 1) + 16 + (22 if legend else 0))
    return Region(x=reg.x, y=reg.y + (reg.h - h) / 2, w=reg.w, h=h)


def _fact_ids(paragraphs: list[Paragraph]) -> list[str]:
    return [p.fact_id for para in paragraphs for p in para.parts if p.type == "fact" and p.fact_id]


def _page(ctx: QuantContext, key: str, sub: str, blocks: list[Block], *, title: Optional[str] = None,
          is_data: bool = True, source_ids: Optional[list[str]] = None, slide_id: Optional[str] = None) -> SlideSpec:
    return SlideSpec(slide_id=slide_id or key, template_id=TEMPLATES[key], page_role="content", section_id="recap",
                     title=title or sub, blocks=_decorate(ctx, [title_block("Diagnosis", sub), *blocks]),
                     source_ids=source_ids or [], is_data=is_data, needs_review=True)


def _plain(paragraphs: list[Paragraph]) -> str:
    return " ".join(p.plain() for p in paragraphs)


def _diag_foot(ctx: QuantContext, fact_ids: list[str], *extra: list[Part]) -> Block:
    return footnote(ctx, list(dict.fromkeys(fact_ids)), [T("채택 자료를 바탕으로 AI가 정리한 진단")], *extra)


# ---------------------------------------------------------------- D1 진단 요약

STATUS_COLOR = {"강점": "navy", "이탈": "accent", "보통": "slate"}


def summary_page(ctx: QuantContext, data: Diagnosis) -> Optional[SlideSpec]:
    """D1: 인지 → 고려 → 탐색 → 구매 → 검증 머리, 단계마다 대표 수치와 상태, 강점·이탈 구간 괄호."""
    brand = ctx.project.brands[0]
    stages = {s.stage: s for s in data.funnel}
    numbers = {s.stage: f for s in data.funnel if s.fact_id and (f := next(iter(_facts(ctx, [s.fact_id])), None))}
    if len(stages) < 3 or len(numbers) < 2:
        return None
    body = region("body")
    gap = 14.0
    col_w = (body.w - gap * 4) / 5
    head_h = 50.0
    y0 = body.y + (body.h - 236) / 2  # heads, numbers, labels, chips and brackets centered in the body
    blocks: list[Block] = []
    fact_ids: list[str] = []
    for i, name in enumerate(STAGES):
        x = body.x + i * (col_w + gap)
        st = stages.get(name)
        fill = STATUS_COLOR[st.status] if st and st.status != "보통" else ("subtle" if st else "slate")
        blocks += [ShapeBlock(block_id=f"d1_head{i}", region=Region(x=x, y=y0, w=col_w, h=head_h), fill=fill),
                   text(f"d1_head{i}_t", Region(x=x, y=y0, w=col_w, h=head_h), [T(name)],
                        align="c", color="white", size=14, weight="bold")]
        if i < len(STAGES) - 1:  # the arrow head between two stages
            blocks.append(text(f"d1_arrow{i}", Region(x=x + col_w - 2, y=y0, w=gap + 4, h=head_h), [T("▶")],
                               align="c", color=fill, size=12))
        if st is None:
            continue
        f = numbers.get(name)
        ny = y0 + head_h + 26
        if f is not None:
            fact_ids.append(f.id)
            blocks.append(text_block(f"d1_num{i}", "body", Region(x=x, y=ny, w=col_w, h=52),
                                     [P(ctx.pf.fact(f, formatter_for(f), bold=True))], spec="caption", align="c",
                                     valign="m", color=STATUS_COLOR.get(st.status, "navy") if st.status != "보통" else "navy",
                                     size=28, line=36, weight="heavy"))
            who = [N(f.entity)] if f.entity and f.entity != brand.name else []
            caption = [*who, *([T(" ")] if who else []), T(st.label or metric_label(f))]
        else:
            caption = [T(st.label)] if st.label else []
        if caption:
            blocks.append(text(f"d1_label{i}", Region(x=x + 6, y=ny + 56, w=col_w - 12, h=36), caption, align="c",
                               color="text", size=10.5, valign="t"))
        chip_w = 54.0
        blocks += [ShapeBlock(block_id=f"d1_chip{i}", region=Region(x=x + (col_w - chip_w) / 2, y=ny + 100, w=chip_w, h=22),
                              shape="rounded", fill="tint" if st.status == "보통" else STATUS_COLOR[st.status]),
                   text(f"d1_chip{i}_t", Region(x=x + (col_w - chip_w) / 2, y=ny + 100, w=chip_w, h=22), [T(st.status)],
                        align="c", color="muted" if st.status == "보통" else "white", size=9.5, weight="bold")]
    # 괄호: consecutive stages with the same 강점/이탈 status share one bracket under the columns.
    by = y0 + head_h + 26 + 140
    runs: list[tuple[str, int, int]] = []
    for i, name in enumerate(STAGES):
        status = stages[name].status if name in stages else None
        if status in ("강점", "이탈") and runs and runs[-1][0] == status and runs[-1][2] == i - 1:
            runs[-1] = (status, runs[-1][1], i)
        elif status in ("강점", "이탈"):
            runs.append((status, i, i))
    for k, (status, a, b) in enumerate(runs):
        x1 = body.x + a * (col_w + gap) + 8
        x2 = body.x + b * (col_w + gap) + col_w - 8
        color = STATUS_COLOR[status]
        blocks += [ShapeBlock(block_id=f"d1_br{k}", region=Region(x=x1, y=by + 10, w=x2 - x1, h=0), shape="line",
                              line=color, line_width=1.5),
                   ShapeBlock(block_id=f"d1_br{k}_l", region=Region(x=x1, y=by, w=0, h=10), shape="line", line=color,
                              line_width=1.5),
                   ShapeBlock(block_id=f"d1_br{k}_r", region=Region(x=x2, y=by, w=0, h=10), shape="line", line=color,
                              line_width=1.5),
                   text(f"d1_br{k}_t", Region(x=x1, y=by + 14, w=x2 - x1, h=22), [T(f"{status} 구간")], align="c",
                        color=color, size=11, weight="bold")]
    cards = []
    for c in data.shown_claims():
        if _known(ctx, c.claim):
            cards.append(([T(KIND_LABEL[c.kind])], [p for para in _fresh(ctx, c.claim, color="navy") for p in para.parts]))
            fact_ids += _fact_ids(c.claim)
    lead = lead_block([P(T(data.profile))] if data.profile else
                      [P(N(brand.name), T(" 구매 여정 진단 — 단계별 강점과 이탈 구간"))])
    return _page(ctx, "D1", "진단 요약", [lead, *blocks, *insight_blocks(cards[:3]), _diag_foot(ctx, fact_ids)])


# ---------------------------------------------------------------- D2 강점·약점 증명

def _labels(facts: list, brand_name: str) -> list[str]:
    """Bar labels: the brand when that alone tells the bars apart, else the readable dims (and month)."""
    names = [f.entity or brand_name for f in facts]
    if len(set(names)) == len(names):
        return names
    out = []
    for f, name in zip(facts, names):
        dims = fact_dims(f)
        month = dims.pop("month", None)
        parts = ([name] if len(set(names)) > 1 else []) + list(dims.values())[:2] + ([month] if month else [])
        out.append(" · ".join(parts) or metric_label(f))
    return out


def claim_chart(ctx: QuantContext, chart, reg: Region, block_id: str = "chart") -> tuple[Optional[Block], list[str]]:
    """The claim's chart from the facts that are still there: (block, fact ids drawn)."""
    if chart is None:
        return None, []
    facts = _facts(ctx, chart.fact_ids)
    if facts:
        facts = [f for f in facts if f.unit == facts[0].unit]
    if len(facts) < 2:
        return None, []
    brand = ctx.project.brands[0]
    fmt = formatter_for(facts[0])
    months = [fact_month(f) for f in facts]
    kind = chart.type
    if kind == "line" and not (all(months) and len(set(months)) == len(facts)
                               and len({(f.metric, f.entity) for f in facts}) == 1
                               and len(facts) >= ctx.config.line_chart_min_points):
        kind = "column"
    if kind == "line":
        ordered = sorted(facts, key=fact_month)
        f0 = ordered[0]
        series = LineSeries(entity=f0.entity or brand.name, role="self" if f0.entity == brand.name else "key",
                            points=[LinePoint(month=fact_month(f), fact_id=f.id, value=float(f.value)) for f in ordered])
        return LineChartBlock(block_id=block_id, region=reg, categories=[fact_month(f) for f in ordered],
                              series=[series]), [f.id for f in ordered]
    entities = {f.entity or brand.name for f in facts}
    number_format = NUMBER_FORMAT.get(fmt, "0.0")
    unit = "percent" if facts[0].unit == "percent" else "count"
    if kind == "stacked":
        parts = list(dict.fromkeys(" · ".join(fact_dims(f).values()) or metric_label(f) for f in facts))
        order = sorted(entities, key=lambda e: (e != brand.name, e))
        if len(order) >= 2 and len(parts) >= 2:
            cell = {(f.entity or brand.name, " · ".join(fact_dims(f).values()) or metric_label(f)): f for f in facts}
            series = [BarSeries(name=part, role="self" if i == 0 else ("key" if i == 1 else "other"), items=[
                BarItem(entity=e, label=part, fact_id=cell[(e, part)].id,
                        display=ctx.pf.fact(cell[(e, part)], fmt).display,
                        value=bar_value(fmt, cell[(e, part)].value), role="other", formatter=fmt)
                if (e, part) in cell else None for e in order]) for i, part in enumerate(parts)]
            block = BarChartBlock(block_id=block_id, region=_fit(reg, len(order), legend=True), categories=order,
                                  series=series, stacked=True, number_format=number_format, unit=unit, label_size=9.5)
            return block, [it.fact_id for it in block.bar_items()]
    if kind == "column" and all(months):
        facts = sorted(facts, key=fact_month)
    items = [BarItem(entity=f.entity or brand.name, label=label, fact_id=f.id,
                     display=ctx.pf.fact(f, fmt).display, value=bar_value(fmt, f.value),
                     role="self" if (f.entity or brand.name) == brand.name else "other", formatter=fmt)
             for f, label in zip(facts, _labels(facts, brand.name))]
    vertical = kind == "column"
    block = BarChartBlock(block_id=block_id, region=reg if vertical else _fit(reg, len(items)), items=items,
                          orientation="v" if vertical else "h", number_format=number_format, unit=unit,
                          label_size=10, gap_width=60 if vertical else 55)
    return block, [it.fact_id for it in block.bar_items()]


def _chart_title(ctx: QuantContext, fact_ids: list[str]) -> list[Part]:
    facts = _facts(ctx, fact_ids)
    names = list(dict.fromkeys(metric_label(f) for f in facts))
    unit = {"percent": "(%)", "count": "(건)"}.get(facts[0].unit, "") if facts else ""
    # Metric labels may include product names such as "6종 패키지". Treat labels as names and
    # reserve plain text for the unit so QC only requires binding for actual numeric claims.
    return [N(" · ".join(names[:2])), T(unit)]


def claim_page(ctx: QuantContext, claim: DiagnosisClaim, materials: list[CaseMaterial], n: int) -> Optional[SlideSpec]:
    """D2: 헤드라인 v2 + 왼쪽 차트 + 오른쪽 원문 카드 + 하단 인사이트. Every headline number is also shown in the body."""
    if claim.excluded or not claim.claim or not _known(ctx, [*claim.claim, *claim.evidence]):
        return None
    by_id = {m.id: m for m in materials}
    quotes = [by_id[i] for i in claim.quote_material_ids
              if i in by_id and by_id[i].review_status == "accepted" and not by_id[i].voc_sponsored][:3]
    body = region("body")
    head_ids = list(dict.fromkeys(_fact_ids([*claim.claim, *claim.evidence])))
    chart_w = body.w * 0.58 if quotes else body.w
    strip_h = 62.0
    probe, drawn = claim_chart(ctx, claim.chart, Region(x=body.x, y=body.y + 44, w=chart_w, h=body.h - 44))
    hidden = [fid for fid in head_ids if fid not in drawn]
    chart_h = body.h - 44 - (strip_h + 8 if hidden else 0)
    chart, drawn = claim_chart(ctx, claim.chart, Region(x=body.x, y=body.y + 44, w=chart_w, h=chart_h))
    if chart is None and not quotes:
        return None
    blocks: list[Block] = []
    if chart is not None:
        blocks += [*_panel_header("chart_header", body.x, body.y, chart_w, _chart_title(ctx, drawn)), chart]
    else:  # quotes only: the cards take the width
        chart_w = 0.0
    # 근거 수치: headline numbers the chart does not draw sit under it as small tiles (QC LEAD_CITES_HIDDEN).
    hidden = [f for f in _facts(ctx, head_ids) if f.id not in drawn][:4]
    if hidden:
        tile_w = (max(chart_w, body.w * 0.58) - 10 * (len(hidden) - 1)) / len(hidden)
        ty = body.y + body.h - strip_h
        for i, f in enumerate(hidden):
            tx = body.x + i * (tile_w + 10)
            blocks += [ShapeBlock(block_id=f"ev{i}_bg", region=Region(x=tx, y=ty, w=tile_w, h=strip_h), fill="tint"),
                       text(f"ev{i}_label", Region(x=tx + 10, y=ty + 6, w=tile_w - 20, h=20),
                            [N(_fit_lines(f"{f.entity} · {metric_label(f)}", tile_w - 20, 9, 1))], color="muted", size=9),
                       text_block(f"ev{i}_value", "body", Region(x=tx + 10, y=ty + 26, w=tile_w - 20, h=30),
                                  [P(ctx.pf.fact(f, formatter_for(f), bold=True))], spec="caption", color="navy",
                                  size=16, line=22, weight="bold", valign="m")]
    if quotes:
        qx = body.x + chart_w + (32 if chart_w else 0)
        qw = body.x + body.w - qx
        blocks += _panel_header("quote_header", qx, body.y, qw, [T("소비자 원문")])
        blocks += quote_cards(quotes, qx, body.y + 44, qw, body.h - 44)
    cards = []
    if isinstance(chart, BarChartBlock):
        for it in sorted(chart.bar_items(), key=lambda it: (it.role != "self", -it.value))[:3]:
            cards.append(([N(_fit_lines(it.label, 330, 10.5, 1))], [N(it.entity), T(" "), ctx.pf.fact(it.fact_id, it.formatter)]))
    elif isinstance(chart, LineChartBlock):  # 처음 · 가장 높은 달 · 최근
        pts = chart.series[0].points
        peak = max(pts, key=lambda p: p.value)
        fmt = formatter_for(ctx.metrics.registry.get(pts[0].fact_id))
        for name, pt in (("처음", pts[0]), ("가장 높은 달", peak), ("최근", pts[-1])):
            cards.append(([T(name)], [N(pt.month), T(" "), ctx.pf.fact(pt.fact_id, fmt)]))
    claim_paras = _fresh(ctx, claim.claim)
    evidence = _fresh(ctx, claim.evidence)
    head = headline_blocks(claim_paras, evidence, region("lead"))
    used = list(dict.fromkeys([*drawn, *head_ids]))
    samples = _facts(ctx, used)
    sub = KIND_LABEL[claim.kind] + " 진단"
    return _page(ctx, "D2", sub, [*head, *blocks, *insight_blocks(cards),
                                  _diag_foot(ctx, used, sample_note([f for f in samples if isinstance(f, Fact)], "원문"))],
                 slide_id=f"D2-{claim.id}", source_ids=[m.source.id for m in quotes],
                 title=f"{sub} · {_fit_lines(_plain(claim_paras), 400, 10, 1)}" if n else sub)


# ---------------------------------------------------------------- D3 경쟁 구도

PRICE_METRIC = "official_price"


def _latest(facts: list) -> dict:
    out: dict = {}
    for f in sorted(facts, key=lambda f: (getattr(f, "measured_at", None) or "", f.id), reverse=True):
        out.setdefault(f.entity, f)
    return out


def competition_page(ctx: QuantContext, materials: list[CaseMaterial], self_names: frozenset[str]) -> Optional[SlideSpec]:
    """D3: 자사와 경쟁사의 공식몰 가격 계층(가격이 있으면) 또는 같은 플랫폼 리뷰 수 격차 + 대표 이미지."""
    brand = ctx.project.brands[0]
    allowed = [brand.name, *[c for c in brand.competitors if c not in self_names]]
    reg = ctx.metrics.registry
    mine = [f for f in reg.facts.values() if f.brand_id == brand.id and f.entity in allowed and usable(f)]
    prices = _latest([f for f in mine if f.metric == PRICE_METRIC])
    reviews_by_platform: dict[str, list] = defaultdict(list)
    for f in mine:
        if f.metric == "review_count" and f.dims.get("platform"):
            reviews_by_platform[f.dims["platform"]].append(f)
    platform = max(reviews_by_platform, key=lambda p: (brand.name in {f.entity for f in reviews_by_platform[p]},
                                                        len({f.entity for f in reviews_by_platform[p]}), p),
                   default=None)
    reviews = {}
    if platform:  # the product with the most reviews per entity on one platform (never mixed platforms)
        for f in sorted(reviews_by_platform[platform], key=lambda f: (f.value, f.id), reverse=True):
            reviews.setdefault(f.entity, f)
    body = region("body")
    images = _images(materials, allowed)
    img_w = 300.0 if images else 0.0
    main_w = body.w - (img_w + 32 if images else 0)
    blocks: list[Block] = []
    fact_ids: list[str] = []
    if brand.name in prices and len(prices) >= 2:
        order = sorted(prices, key=lambda e: (-prices[e].value, e))
        columns = [TableColumn(key="tier", label="가격 계층", width=0.2), TableColumn(key="who", label="브랜드", width=0.3),
                   TableColumn(key="price", label="공식몰 가격", width=0.25), TableColumn(key="reviews", label="리뷰 수", width=0.25)]
        n = len(order)
        rows = []
        for i, e in enumerate(order):
            tier = "상" if i < n / 3 else ("중" if i < 2 * n / 3 else "하")
            fp = prices[e]
            cells = [TableCell(paragraphs=[P(T(tier))]), TableCell(paragraphs=[P(N(e), bold=e == brand.name)]),
                     TableCell(paragraphs=[P(ctx.pf.fact(fp, "krw", bold=e == brand.name))])]
            fact_ids.append(fp.id)
            if e in reviews:
                cells.append(TableCell(paragraphs=[P(ctx.pf.fact(reviews[e], "int"))]))
                fact_ids.append(reviews[e].id)
            else:
                cells.append(TableCell(paragraphs=[P(T("—"), color="muted")]))
            rows.append(TableRow(cells=cells, muted=False, ref=e))
        row_h = min(56.0, (body.h - 32) / n)
        blocks += [*_panel_header("table_header", body.x, body.y, main_w, [T("공식몰 가격 계층")]),
                   TableBlock(block_id="table", region=Region(x=body.x, y=body.y + 44, w=main_w, h=32 + row_h * n),
                              columns=columns, rows=rows, row_height=row_h, header_height=32)]
        lead = [P(N(brand.name), T(" 가격 위치 — 경쟁사 대비 공식몰 가격 계층과 리뷰 수"))]
    elif brand.name in reviews and len(reviews) >= 2:
        order = [brand.name, *sorted((e for e in reviews if e != brand.name), key=lambda e: (-reviews[e].value, e))]
        items = [BarItem(entity=e, label=e, fact_id=reviews[e].id, display=ctx.pf.fact(reviews[e], "int").display,
                         value=bar_value("int", reviews[e].value), role="self" if e == brand.name else "other",
                         formatter="int") for e in order]
        chart = BarChartBlock(block_id="chart", region=_fit(Region(x=body.x, y=body.y + 44, w=main_w, h=body.h - 44),
                                                            len(items)),
                              items=items, number_format=COUNT_FORMAT, unit="count", label_size=10.5)
        fact_ids += [it.fact_id for it in items]
        from core.composition.commerce import PLATFORM_LABEL
        where = PLATFORM_LABEL.get(platform, platform)
        blocks += [*_panel_header("chart_header", body.x, body.y, main_w, [N(where), T(" 대표 상품 리뷰 수(건)")]), chart]
        lead = [P(N(brand.name), T(" vs 경쟁사 — "), N(where), T(" 리뷰 수 격차"))]
        blocks += insight_blocks([([N(e)], [T("리뷰 "), ctx.pf.fact(reviews[e], "int"), T("건")]) for e in order[:3]])
    else:
        return None
    if images:
        blocks += _image_column(images, body.x + main_w + 32, body.y, img_w, body.h)
    return _page(ctx, "D3", "경쟁 구도", [lead_block(lead), *blocks, _diag_foot(ctx, fact_ids)],
                 source_ids=[m.source.id for _, m in images])


def _images(materials: list[CaseMaterial], allowed: list[str]) -> list[tuple[AssetRef, CaseMaterial]]:
    """One accepted image per brand (self first, then competitors in project order), at most three."""
    out: list[tuple[AssetRef, CaseMaterial]] = []
    for name in allowed:
        m = next((m for m in sorted(materials, key=lambda m: (m.order, m.id)) if m.entity == name
                  and m.review_status == "accepted" and m.asset and m.asset.review_status == "accepted"), None)
        if m:
            out.append((m.asset, m))
    return out[:3]


def _image_column(images: list[tuple[AssetRef, CaseMaterial]], x: float, y: float, w: float, h: float) -> list[Block]:
    blocks: list[Block] = []
    gap, cap = 10.0, 22.0
    cell_h = (h - gap * (len(images) - 1)) / len(images)
    for i, (asset, m) in enumerate(images):
        cy = y + i * (cell_h + gap)
        blocks += [ImageBlock(block_id=f"img{i}", region=Region(x=x, y=cy, w=w, h=cell_h - cap), asset_id=asset.id,
                              crop=asset.crop),
                   text(f"img{i}_cap", Region(x=x, y=cy + cell_h - cap, w=w, h=cap), [N(m.entity or "")], color="muted",
                        size=9)]
    return blocks


# ---------------------------------------------------------------- D4 CDJ 시사점

def cdj_page(ctx: QuantContext, data: Diagnosis) -> Optional[SlideSpec]:
    """D4: 단계 × (고객 접점, 인지 상태 칩, 인지 증대 활동)."""
    rows_src = [r for r in data.cdj if r.stage][:6]
    if len(rows_src) < 3:
        return None
    brand = ctx.project.brands[0]
    body = region("body")
    columns = [TableColumn(key="stage", label="단계", width=0.14), TableColumn(key="touch", label="고객 접점", width=0.26, align="l"),
               TableColumn(key="state", label="인지 상태", width=0.26), TableColumn(key="activity", label="인지 증대 활동", width=0.34, align="l")]
    rows = [TableRow(cells=[TableCell(paragraphs=[P(T(r.stage))], fill="navy", color="white", bold=True),
                            TableCell(paragraphs=[P(T(r.touchpoint or "—"))]),
                            TableCell(paragraphs=[P(T(r.state or "—"))], fill="pale", bold=True, color="navy"),
                            TableCell(paragraphs=[P(T(r.activity or "—"))])]) for r in rows_src]
    row_h = min(110.0, (body.h - 32) / len(rows))
    table = TableBlock(block_id="table", region=Region(x=body.x, y=body.y, w=body.w, h=32 + row_h * len(rows)),
                       columns=columns, rows=rows, row_height=row_h, header_height=32, size=11, header_size=10.5)
    lead = lead_block([P(N(brand.name), T(" 고객 의사결정 여정 — 단계별 접점과 인지를 키울 활동"))])
    foot = footnote_block([P(T("*채택 자료를 바탕으로 AI가 정리한 고객 의사결정 여정(CDJ)"))])
    return _page(ctx, "D4", "CDJ 시사점", [lead, table, foot], is_data=False)


# ---------------------------------------------------------------- D5 활동 제안

def actions_page(ctx: QuantContext, data: Diagnosis) -> Optional[SlideSpec]:
    """D5: 소셜·인플루언서·콘텐츠 열마다 제안 카드(제목, CDJ 칩, 근거 한 줄). 근거가 지금 없는 제안은 뺀다."""
    by_pillar: dict[str, list] = defaultdict(list)
    for p in data.proposals:
        if p.basis and _known(ctx, p.basis) and _facts(ctx, p.basis_fact_ids):
            by_pillar[p.pillar].append(p)
    pillars = [x for x in PILLARS if by_pillar.get(x)]
    if sum(len(v) for v in by_pillar.values()) < 2:
        return None
    brand = ctx.project.brands[0]
    body = region("body")
    gap = 24.0
    col_w = (body.w - gap * (len(pillars) - 1)) / len(pillars)
    blocks: list[Block] = []
    fact_ids: list[str] = []
    for i, pillar in enumerate(pillars):
        x = body.x + i * (col_w + gap)
        blocks += [ShapeBlock(block_id=f"d5_head{i}", region=Region(x=x, y=body.y, w=col_w, h=40), fill="navy"),
                   text_block(f"d5_head{i}_t", "panel_header", Region(x=x, y=body.y, w=col_w, h=40), [P(T(pillar))],
                              spec="pillar_header", align="c", valign="m", color="white")]
        cards = by_pillar[pillar][:2]
        card_h = (body.h - 52 - 12 * (len(cards) - 1)) / len(cards)
        for k, p in enumerate(cards):
            cy = body.y + 52 + k * (card_h + 12)
            bid = f"d5_{i}_{k}"
            blocks.append(ShapeBlock(block_id=f"{bid}_bg", region=Region(x=x, y=cy, w=col_w, h=card_h), fill="tint"))
            content_h = (30 if p.cdj_stage else 0) + 50 + 12 + 40
            ty = cy + max(14.0, (card_h - content_h) / 2)
            if p.cdj_stage:
                chip_w = min(col_w - 28, 24 + 11 * len(p.cdj_stage))
                blocks += [ShapeBlock(block_id=f"{bid}_chip", region=Region(x=x + 14, y=ty, w=chip_w, h=22), shape="rounded",
                                      fill="pale"),
                           text(f"{bid}_chip_t", Region(x=x + 14, y=ty, w=chip_w, h=22), [T(p.cdj_stage)], align="c",
                                color="navy", size=9.5, weight="bold")]
                ty += 30
            blocks.append(text_block(f"{bid}_title", "body", Region(x=x + 14, y=ty, w=col_w - 28, h=50),
                                     [P(T(p.title))], spec="pillar_body", weight="bold", color="navy", size=16, line=22))
            basis = _fresh(ctx, p.basis[:1])
            blocks += [ShapeBlock(block_id=f"{bid}_rule", region=Region(x=x + 14, y=ty + 56, w=col_w - 28, h=0),
                                  shape="line", line="rule", line_width=0.5),
                       text_block(f"{bid}_basis", "body", Region(x=x + 14, y=ty + 62, w=col_w - 28, h=40),
                                  [P(T("근거 ", color="muted"), *basis[0].parts)], spec="card_body", size=10, line=14)]
            fact_ids += _fact_ids(basis)
    lead = lead_block([P(N(brand.name), T(" 활동 제안 — " + "·".join(pillars) + "에서 끊긴 구간을 잇는 활동"))])
    return _page(ctx, "D5", "활동 제안", [lead, *blocks, _diag_foot(ctx, fact_ids)])


# ---------------------------------------------------------------- D6 결론

def conclusion_page(ctx: QuantContext, diagnoses: dict[str, Diagnosis]) -> Optional[SlideSpec]:
    """D6: 자사 브랜드 × 끊긴 구간 × 소셜·인플루언서·콘텐츠. Brands keep the project order — no ranking or score."""
    rows: list[TableRow] = []
    for b in ctx.project.brands:
        d = diagnoses.get(b.id)
        if d is None:
            continue
        cut = [s.stage for s in d.funnel if s.status == "이탈"]
        weak = [c for c in d.shown_claims("weakness") if _known(ctx, c.claim)]
        if not cut and not weak:
            continue
        per = {x: [p.title for p in d.proposals if p.pillar == x][:2] for x in PILLARS}
        if not any(per.values()):
            continue
        cut_cell = [P(T(" → ".join(cut)), bold=True, color="accent")] if cut else []
        if weak:
            cut_cell.append(P(*[p for para in _fresh(ctx, weak[0].claim) for p in para.parts if p.type != "fact"],
                              color="text"))
        cells = [TableCell(paragraphs=[P(N(b.name), bold=True)], fill="tint"), TableCell(paragraphs=cut_cell, align="l")]
        for x in PILLARS:
            cells.append(TableCell(paragraphs=[P(T(t), bullet="·") for t in per[x]] or [P(T("—"), color="muted")],
                                   align="l"))
        rows.append(TableRow(cells=cells, ref=b.id))
    if not rows:
        return None
    body = region("body")
    columns = [TableColumn(key="brand", label="자사 브랜드", width=0.14),
               TableColumn(key="cut", label="끊긴 구간", width=0.26, align="l"),
               *[TableColumn(key=f"p{i}", label=x, width=0.2, align="l") for i, x in enumerate(PILLARS)]]
    row_h = min(180.0, (body.h - 32) / len(rows))
    table = TableBlock(block_id="table", region=Region(x=body.x, y=body.y, w=body.w, h=32 + row_h * len(rows)),
                       columns=columns, rows=rows, row_height=row_h, header_height=32, size=10, header_size=10.5)
    lead = lead_block([P(T("결론 — 브랜드마다 끊긴 구간과 소셜·인플루언서·콘텐츠 활동 방향"))])
    foot = footnote_block([P(T("*브랜드별 진단을 나란히 정리(브랜드 간 순위·점수 비교 아님) · 채택 자료를 바탕으로 AI가 정리"))])
    return SlideSpec(slide_id="D6", template_id=TEMPLATES["D6"], page_role="content", section_id="recap", title="결론",
                     blocks=_decorate(ctx, [title_block("Diagnosis", "결론"), lead, table, foot]), is_data=False,
                     needs_review=True)


def parse(data) -> Optional[Diagnosis]:
    """Stored diagnosis dict (BuildInputs.diagnosis) → Diagnosis, None if it can't be read."""
    if not data:
        return None
    try:
        return data if isinstance(data, Diagnosis) else Diagnosis.model_validate(data)
    except ValueError:
        return None
