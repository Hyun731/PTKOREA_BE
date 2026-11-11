"""자사 vs 경쟁사 비교 장표 (P3-1 OW-CMP, P3-3 MN1 채널별 언급량 · BL1 블로그 문서 유형).

한 장에는 자사 브랜드 하나와 그 브랜드의 경쟁사만 둔다(원칙 8: 자사 브랜드끼리 비교하지 않는다).
숫자는 모두 확인된(eligible) Fact 또는 그 Fact에서 계산한 파생값이고, 막대 하나하나가 fact_id를
달고 있어 바인딩·QC가 그대로 확인한다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from core.composition.chrome import D, M, N, P, PERIOD, T, footnote_block, insight_blocks, lead_block, text_block, title_block
from core.composition.quant import QuantContext, _decorate, _measured, _panel_header
from core.composition.tokens import region
from core.metrics.derived import footnote_label
from core.schemas.facts import DerivedFact, Fact
from core.schemas.project import Brand
from core.schemas.slidespec import (
    BarChartBlock, BarItem, BarSeries, Block, Part, Region, ShapeBlock, SlideSpec,
)

# 장표에 쓰는 출처 이름(원본 Fact.source → 읽는 사람용)
SOURCE_NAMES = {"derived": "채택 자료 AI 분류", "synthetic_fixture": "합성 테스트 자료(synthetic_fixture)",
                "scrapecreators": "공개 게시물 관측값(ScrapeCreators)"}
# 막대 라벨: 1만 이상은 '3.5만'처럼 줄여 좁은 막대에도 들어가게(값 자체는 그대로 — 0"."0, 는 천 단위로 나눈 뒤
# 마지막 자리 앞에 점을 찍는 표기라 35,210 → 3.5만). 바인딩·QC는 Fact를 정식 표기(display)로 확인한다.
COUNT_FORMAT = '[>=10000]0"."0,"만";#,##0'
NUMBER_FORMATS = {"count": COUNT_FORMAT, "int": COUNT_FORMAT, "index": "0.0", "share": '0.0"%"'}
SENTIMENT = [("positive", "긍정", "navy"), ("neutral", "중립", "slate"), ("negative", "부정", "red")]


# ---------------------------------------------------------------- 공통 도우미

def usable(f) -> bool:
    """장표에 올려도 되는 값: 사람이 확인한(eligible) Fact, 또는 그런 Fact로 계산한 파생값."""
    if isinstance(f, DerivedFact):
        return f.value is not None and f.confidence != "missing"
    return f.usable and f.conflict_key is None


def facts_of(ctx: QuantContext, metric: str, brand_id: Optional[str] = None, **dims: str) -> list[Fact]:
    """usable Facts of one metric (optionally one brand and exact dims), newest first."""
    out = [f for f in ctx.metrics.registry.facts.values()
           if f.metric == metric and (brand_id is None or f.brand_id == brand_id) and usable(f)
           and all(f.dims.get(k) == v for k, v in dims.items())]
    return sorted(out, key=lambda f: (f.measured_at, f.id), reverse=True)


def latest_by(facts: Iterable[Fact], key) -> dict:
    """The newest Fact per key(f) (facts must already be newest first)."""
    out: dict = {}
    for f in facts:
        out.setdefault(key(f), f)
    return out


def bar_value(formatter: str, value: Decimal) -> float:
    """Chart data value at the precision the label shows."""
    places = {"count": 0, "int": 0, "index": 1, "share": 1}.get(formatter, 1)
    return float(round(Decimal(value), places))


def bar_item(ctx: QuantContext, entity: str, label: str, fact, formatter: str, role: str = "other") -> BarItem:
    return BarItem(entity=entity, label=label, fact_id=fact.id, display=ctx.pf.fact(fact, formatter).display,
                   value=bar_value(formatter, fact.value), role=role, formatter=formatter)


def source_names(ctx: QuantContext, fact_ids: list[str]) -> list[str]:
    names: list[str] = []
    for fid in fact_ids:
        for raw in ctx.metrics.registry.lineage(fid):
            src = ctx.metrics.registry.facts[raw].source
            name = SOURCE_NAMES.get(src, src)
            if name not in names:
                names.append(name)
    return names


def footnote(ctx: QuantContext, fact_ids: list[str], *extra: list[Part]) -> Block:
    """'*기간 · 정의 · 측정일 · 출처' — every chart page carries it (QC FOOTNOTE_MISSING)."""
    parts: list[Part] = [T("*"), PERIOD(ctx.project.period.start, ctx.project.period.end)]
    for chunk in extra:
        if chunk:
            parts += [T(" · "), *chunk]
    measured = _measured(ctx, fact_ids)
    if measured:
        parts += [T(" · 측정 "), D(measured)]
    names = source_names(ctx, fact_ids)
    if names:
        parts += [T(" · " + " · ".join(names))]
    return footnote_block([P(*parts)])


def sample_note(facts: list, what: str) -> list[Part]:
    """'댓글 감성 n=24~310 · AI 분류' for AI-classified share facts (sample size n lives in dims)."""
    ns = sorted({int(f.dims["n"]) for f in facts if footnote_label(f) or "n" in f.dims})
    if not ns:
        return []
    n = f"n={ns[0]}" if len(ns) == 1 else f"n={ns[0]}~{ns[-1]}"
    return [M(f"{what} {n} · AI 분류", "sample")]


ROW_MAX = 200.0  # one channel row at most — a lone channel would otherwise stretch to the whole body
BAR_ROW_MAX = 30.0  # px per bar at most — a tall cell with two bars should not draw two slabs


def fit_bars(reg: Region, n: int, legend: bool = False) -> Region:
    """The chart's own box inside a cell: at most BAR_ROW_MAX per bar, vertically centered."""
    h = min(reg.h, BAR_ROW_MAX * max(n, 1) + 16 + (22 if legend else 0))
    return Region(x=reg.x, y=reg.y + (reg.h - h) / 2, w=reg.w, h=h)


def text(block_id: str, reg: Region, parts: list[Part], *, spec: str = "caption", align: str = "l",
         color: str = "text", valign: str = "m", size: Optional[float] = None, weight: Optional[str] = None):
    return text_block(block_id, "caption", reg, [P(*parts)], spec=spec, align=align, valign=valign, color=color,
                      size=size, line=round((size or 9.5) * 1.35, 1), weight=weight)


# ---------------------------------------------------------------- OW-CMP 자사 vs 경쟁사 채널 비교

CHANNELS = [("instagram", "Instagram"), ("youtube", "YouTube"), ("tiktok", "TikTok"), ("facebook", "Facebook"),
            ("x", "X"), ("threads", "Threads"), ("naver_blog", "네이버 블로그")]
CHANNEL_LABEL = dict(CHANNELS)
CHANNELS_PER_PAGE = 4  # 채널이 4개를 넘으면 다음 장으로 이어서
MAX_COMPETITORS = 4  # 막대가 읽히는 한도: 자사 + 경쟁사 4곳
FORMAT_LABEL = {"video": "동영상", "shorts": "쇼츠"}


@dataclass
class KpiCell:
    rows: list[tuple[str, object]]  # (entity, fact) in display order, self first
    note: Optional[str] = None  # e.g. 'YouTube 조회: 쇼츠 기준'


# column key -> (header, short name for insights, formatter, metrics tried in order)
KPI_COLUMNS = [
    ("followers", "팔로워", "팔로워", "count", ["owned_followers"]),
    ("posts", "월 게시 수", "월 게시 수", "index", ["owned_posts_monthly", "owned_videos_monthly"]),
    ("engagement", "게시물당 반응(중앙값)", "게시물당 반응", "count", ["owned_likes_median", "owned_reactions_median",
                                                                 "owned_comments_median"]),
    ("views", "평균 조회수", "평균 조회수", "count", ["owned_views_avg", "owned_views_median"]),
]
ENGAGEMENT_NAME = {"owned_likes_median": "좋아요", "owned_reactions_median": "반응", "owned_comments_median": "댓글"}


def _entities(brand: Brand, exclude: frozenset[str]) -> list[str]:
    comps = [c for c in brand.competitors if c != brand.name and c not in exclude]
    return [brand.name, *comps]


def _by_format(facts: list[Fact], entities: list[str], self_name: str) -> tuple[dict[str, Fact], Optional[str]]:
    """One fact per entity from the format group most entities share (video vs shorts) — never mixed."""
    groups: dict[Optional[str], dict[str, Fact]] = defaultdict(dict)
    for f in facts:
        if f.entity in entities:
            groups[f.dims.get("format")].setdefault(f.entity, f)
    if not groups:
        return {}, None
    order = {None: 0, "video": 1, "shorts": 2}
    fmt = max(groups, key=lambda g: (len(groups[g]), self_name in groups[g], -order.get(g, 3)))
    return groups[fmt], fmt


def _youtube_uploads(ctx: QuantContext, brand: Brand, entities: list[str]) -> dict[str, object]:
    """YouTube 월 게시 수 = 월평균 동영상 + 쇼츠 (두 Fact의 합을 파생값으로 — 출처는 두 Fact)."""
    out: dict[str, object] = {}
    facts = facts_of(ctx, "owned_videos_monthly", brand.id, channel="youtube")
    for e in entities:
        parts = latest_by((f for f in facts if f.entity == e), lambda f: f.dims.get("format"))
        if not parts:
            continue
        total = sum((f.value for f in parts.values()), Decimal(0))
        out[e] = ctx.metrics.registry.derive(
            "owned_uploads_monthly_sum", [f.id for f in parts.values()], brand_id=brand.id, entity=e,
            metric="owned_uploads_monthly", value=total, unit="count",
            definition="YouTube 월평균 업로드 = 동영상 + 쇼츠")
    return out


def _kpi_cell(ctx: QuantContext, brand: Brand, entities: list[str], channel: str, key: str,
              metrics: list[str]) -> Optional[KpiCell]:
    for metric in metrics:
        if key == "posts" and metric == "owned_videos_monthly":
            if channel != "youtube":
                continue
            found, fmt = _youtube_uploads(ctx, brand, entities), None
        else:
            found, fmt = _by_format(facts_of(ctx, metric, brand.id, channel=channel), entities, brand.name)
        rows = [(e, found[e]) for e in entities if e in found]
        if brand.name in found and len(rows) >= 2:
            note = None
            if fmt in FORMAT_LABEL:
                note = f"{FORMAT_LABEL[fmt]} 기준"
            elif key == "engagement" and metric != "owned_likes_median":
                note = f"{ENGAGEMENT_NAME[metric]} 기준"
            return KpiCell(rows=rows[:1 + MAX_COMPETITORS], note=note)
    return None


def _sentiment(ctx: QuantContext, brand: Brand, entities: list[str], channel: str) -> list[tuple[str, dict]]:
    """[(entity, {polarity: fact})] for entities with all three comment-sentiment rates on this channel."""
    facts = facts_of(ctx, "comment_sentiment_rate", brand.id, channel=channel)
    out = []
    for e in entities:
        pols = latest_by((f for f in facts if f.entity == e), lambda f: f.dims.get("polarity"))
        if all(p in pols for p, _, _ in SENTIMENT):
            out.append((e, pols))
    return out[:1 + MAX_COMPETITORS]


def channel_compare_data(ctx: QuantContext, brand: Brand, exclude: frozenset[str] = frozenset()) -> list[dict]:
    """Per channel (in CHANNELS order): {"channel", "kpis": {key: KpiCell}, "sentiment": [...]}.
    A channel is kept only when the self brand and at least one competitor both have a number there."""
    entities = _entities(brand, exclude)
    out = []
    for channel, _ in CHANNELS:
        kpis = {}
        for key, _, _, _, metrics in KPI_COLUMNS:
            cell = _kpi_cell(ctx, brand, entities, channel, key, metrics)
            if cell:
                kpis[key] = cell
        if kpis:
            out.append({"channel": channel, "kpis": kpis, "sentiment": _sentiment(ctx, brand, entities, channel)})
    return out


def _kpi_chart(ctx: QuantContext, block_id: str, reg: Region, cell: KpiCell, formatter: str, self_name: str,
               label_size: float) -> BarChartBlock:
    comps = [(e, f) for e, f in cell.rows if e != self_name]
    top = max(comps, key=lambda r: r[1].value)[0] if comps else None
    items = [bar_item(ctx, e, e, f, formatter, "self" if e == self_name else ("key" if e == top else "other"))
             for e, f in cell.rows]
    n = len(items)
    gap = 40 if reg.h / max(n, 1) < 22 else 70
    return BarChartBlock(block_id=block_id, region=reg, items=items, number_format=NUMBER_FORMATS[formatter],
                         unit=formatter, label_size=label_size, gap_width=gap)


def _sentiment_chart(ctx: QuantContext, block_id: str, reg: Region, rows: list[tuple[str, dict]],
                     label_size: float) -> BarChartBlock:
    cats = [e for e, _ in rows]
    series = [BarSeries(name=label, color=color,
                        items=[bar_item(ctx, e, e, pols[pol], "share") for e, pols in rows])
              for pol, label, color in SENTIMENT]
    return BarChartBlock(block_id=block_id, region=reg, categories=cats, series=series, stacked=True,
                         number_format='0"%"', unit="percent", label_size=label_size, gap_width=50)


def _insights(ctx: QuantContext, brand: Brand, channels: list[dict]) -> list[tuple[list[Part], list[Part]]]:
    """Numbered insights from the page's own numbers: self vs the highest competitor, one KPI per channel
    first, then more KPIs until three. Facts only — no judgment words (P3-5 may rewrite these)."""
    pairs = []
    for rnd in range(len(KPI_COLUMNS)):
        for ch in channels:
            keys = [k for k, *_ in KPI_COLUMNS if k in ch["kpis"]]
            if rnd < len(keys):
                pairs.append((ch, keys[rnd]))
    out = []
    names = {k: short for k, _, short, _, _ in KPI_COLUMNS}
    fmts = {k: fmt for k, _, _, fmt, _ in KPI_COLUMNS}
    for ch, key in pairs[:3]:
        cell: KpiCell = ch["kpis"][key]
        own = next(f for e, f in cell.rows if e == brand.name)
        comp_e, comp_f = max(((e, f) for e, f in cell.rows if e != brand.name), key=lambda r: r[1].value)
        title = [N(CHANNEL_LABEL[ch["channel"]]), T(f" {names[key]}")]
        body = [N(brand.name), T(" "), ctx.pf.fact(own, fmts[key], bold=True), T(" · 경쟁사 중 가장 높은 "), N(comp_e),
                T(" "), ctx.pf.fact(comp_f, fmts[key], bold=False)]
        out.append((title, body))
    return out


def channel_compare_pages(ctx: QuantContext, exclude: frozenset[str] = frozenset()) -> list[SlideSpec]:
    """OW-CMP: 자사 하나 + 그 경쟁사, 채널마다 한 줄(팔로워·월 게시 수·게시물당 반응·조회 막대 + 댓글 감성 누적 막대)."""
    brand = ctx.project.brands[0] if len(ctx.project.brands) == 1 else None
    if brand is None:  # several self brands in one context would put them on one page — never (원칙 8)
        return []
    channels = channel_compare_data(ctx, brand, exclude)
    if not channels:
        return []
    pages = []
    chunks = [channels[i:i + CHANNELS_PER_PAGE] for i in range(0, len(channels), CHANNELS_PER_PAGE)]
    for page_i, chunk in enumerate(chunks):
        sid = "OW-CMP" + (f"-p{page_i + 1}" if page_i else "")
        pages.append(_compare_page(ctx, brand, chunk, sid, parent="OW-CMP" if page_i else None))
    return pages


def _compare_page(ctx: QuantContext, brand: Brand, channels: list[dict], slide_id: str,
                  parent: Optional[str]) -> SlideSpec:
    body = region("body")
    cols = [(k, header, fmt) for k, header, _, fmt, _ in KPI_COLUMNS if any(k in ch["kpis"] for ch in channels)]
    has_sent = any(ch["sentiment"] for ch in channels)
    if has_sent:
        cols.append(("sentiment", "댓글 감성(긍정·중립·부정)", "share"))
    label_w, gap, head_h, row_gap = 120.0, 14.0, 26.0, 10.0
    col_w = (body.w - label_w - gap * len(cols)) / len(cols)
    n = len(channels)
    row_h = min(ROW_MAX, (body.h - head_h - 6 - row_gap * (n - 1)) / n)
    label_pt = 10.0 if row_h >= 120 else 9.0
    blocks: list[Block] = []
    fact_ids: list[str] = []
    xs = [body.x + label_w + gap + i * (col_w + gap) for i in range(len(cols))]
    for (key, header, _), x in zip(cols, xs):
        blocks.append(ShapeBlock(block_id=f"col_{key}_bg", region=Region(x=x, y=body.y, w=col_w, h=head_h),
                                 fill="tint"))
        blocks.append(text(f"col_{key}_head", Region(x=x, y=body.y, w=col_w, h=head_h), [T(header)], align="c",
                           color="navy", weight="semibold"))
    sent_facts: list = []
    for r, ch in enumerate(channels):
        y = body.y + head_h + 6 + r * (row_h + row_gap)
        notes = [c.note for c in ch["kpis"].values() if c.note]
        blocks.append(ShapeBlock(block_id=f"row{r}_bg", region=Region(x=body.x, y=y, w=label_w, h=row_h),
                                 fill="panel_header"))
        label = [P(N(CHANNEL_LABEL[ch["channel"]], bold=True))]
        if notes:
            label.append(P(T(" · ".join(dict.fromkeys(notes)), size=8.5, color="slate")))
        blocks.append(text_block(f"row{r}_label", "panel_header", Region(x=body.x + 6, y=y, w=label_w - 12, h=row_h),
                                 label, spec="panel_header", align="c", valign="m", color="white"))
        blocks.append(ShapeBlock(block_id=f"row{r}_rule", region=Region(x=body.x + label_w, y=y + row_h + row_gap / 2,
                                                                         w=body.w - label_w, h=0),
                                 shape="line", line="rule", line_width=0.5))
        for (key, _, fmt), x in zip(cols, xs):
            reg = Region(x=x, y=y, w=col_w, h=row_h)
            if key == "sentiment":
                if ch["sentiment"]:
                    chart = _sentiment_chart(ctx, f"row{r}_{key}", fit_bars(reg, len(ch["sentiment"]), legend=True),
                                             ch["sentiment"], label_pt - 0.5)
                    blocks.append(chart)
                    fact_ids += [it.fact_id for it in chart.bar_items()]
                    sent_facts += [f for _, pols in ch["sentiment"] for f in pols.values()]
                    continue
            elif key in ch["kpis"]:
                cell = ch["kpis"][key]
                chart = _kpi_chart(ctx, f"row{r}_{key}", fit_bars(reg, len(cell.rows)), cell, fmt, brand.name, label_pt)
                blocks.append(chart)
                fact_ids += [it.fact_id for it in chart.bar_items()]
                continue
            blocks.append(text(f"row{r}_{key}_empty", reg, [T("—")], align="c", color="muted"))

    items = _insights(ctx, brand, channels)
    for _, body_parts in items:
        fact_ids += [p.fact_id for p in body_parts if p.type == "fact"]
    lead = lead_block([P(N(brand.name), T(" vs 경쟁사 공식 채널 — 팔로워·게시 빈도·게시물당 반응 비교"))])
    defs = [T("공식 계정 공개 지표 · 반응·조회는 기간 내 게시물 기준")]
    blocks = [
        title_block("Owned", "자사 vs 경쟁사 채널 비교"), lead, *blocks, *insight_blocks(items),
        footnote(ctx, fact_ids, defs, sample_note(sent_facts, "댓글 감성")),
    ]
    return SlideSpec(slide_id=slide_id, template_id="channel_compare.v1", page_role="content", section_id="owned",
                     title="자사 vs 경쟁사 채널 비교", blocks=_decorate(ctx, blocks), parent_slide_id=parent,
                     needs_review=True, is_data=True)


# ---------------------------------------------------------------- 공통: 한 자사 브랜드만

def single_brand(ctx: QuantContext) -> Optional[Brand]:
    """These pages are per self brand; a context holding several would put them on one page (원칙 8)."""
    return ctx.project.brands[0] if len(ctx.project.brands) == 1 else None


def vs_top(ctx: QuantContext, own_name: str, own, others: list[tuple[str, object]], formatter: str, what: str,
           title: list[Part]) -> Optional[tuple[list[Part], list[Part]]]:
    """Numbered insight 'title / 자사 X · 경쟁사 중 가장 높은 Y Z' from the page's own facts."""
    if own is None or not others:
        return None
    comp, comp_f = max(others, key=lambda r: r[1].value)
    return title, [N(own_name), T(" "), ctx.pf.fact(own, formatter, bold=True), T(f" · 경쟁사 중 가장 {what} "), N(comp),
                   T(" "), ctx.pf.fact(comp_f, formatter, bold=False)]


COMPETITOR_COLORS = ["red", "line_other", "bar_other", "gold"]  # 첫 경쟁사(가장 큰 곳)는 강조색


# ---------------------------------------------------------------- MN1 채널별 언급량 비교 (P3-3)

MENTION_CHANNELS = [("blog", "블로그"), ("cafe", "카페"), ("news", "뉴스"), ("kin", "지식iN")]
MENTION_MIN_CHANNELS = 2  # 채널 하나뿐이면 '채널별' 비교가 아니다


def _group_label(group: str, cells: dict, brand: Brand) -> str:
    if group == "brand":
        return "브랜드명"
    kw = next((f.dims.get("keyword") for (e, _), f in cells.items() if e == brand.name and f.dims.get("keyword")), "")
    rest = kw.replace(brand.name, "").strip()
    return f"브랜드 + {rest}" if rest else group


def mention_page(ctx: QuantContext, exclude: frozenset[str] = frozenset()) -> Optional[SlideSpec]:
    """MN1: 자사 + 경쟁사 × 블로그·카페·뉴스(·지식iN) 검색 결과 문서 수(누적) 묶음 막대. 검색어 묶음
    (브랜드명 / 브랜드+제품군)마다 패널 하나, 최대 2개. 자사와 경쟁사 1곳 이상이 2개 채널 이상에 있어야 만든다."""
    brand = single_brand(ctx)
    if brand is None:
        return None
    entities = _entities(brand, exclude)[:1 + MAX_COMPETITORS]
    groups: dict[str, dict] = defaultdict(dict)
    for f in facts_of(ctx, "mention_total", brand.id):
        if f.entity in entities and f.dims.get("channel") in dict(MENTION_CHANNELS):
            groups[f.dims.get("keyword_group") or "brand"].setdefault((f.entity, f.dims["channel"]), f)
    panels = []
    for group in sorted(groups, key=lambda g: (g != "brand", g)):
        cells = groups[group]
        chans = [c for c, _ in MENTION_CHANNELS if (brand.name, c) in cells and
                 any((e, c) in cells for e in entities if e != brand.name)]
        ents = [e for e in entities if any((e, c) in cells for c in chans)]
        if len(chans) >= MENTION_MIN_CHANNELS and len(ents) >= 2:
            panels.append((group, chans, ents, cells))
    if not panels:
        return None
    panels = panels[:2]
    body = region("body")
    gap = 40.0
    w = (body.w - gap * (len(panels) - 1)) / len(panels)
    blocks: list[Block] = []
    fact_ids: list[str] = []
    labels = dict(MENTION_CHANNELS)
    for i, (group, chans, ents, cells) in enumerate(panels):
        x = body.x + i * (w + gap)
        blocks += _panel_header(f"panel{i}_header", x, body.y, w, [T(_group_label(group, cells, brand)),
                                                                   T(" · 검색 결과 문서 수")])
        comps = sorted((e for e in ents if e != brand.name), key=lambda e: -sum(cells[(e, c)].value for c in chans
                                                                                if (e, c) in cells))
        colors = dict(zip(comps, COMPETITOR_COLORS))
        series = [BarSeries(name=e, role="self" if e == brand.name else "other", color=None if e == brand.name else colors[e],
                            items=[bar_item(ctx, e, labels[c], cells[(e, c)], "count") if (e, c) in cells else None
                                   for c in chans])
                  for e in ents]
        chart = BarChartBlock(block_id=f"panel{i}_chart", region=Region(x=x, y=body.y + 48, w=w, h=body.h - 48),
                              categories=[labels[c] for c in chans], series=series, orientation="v",
                              number_format=COUNT_FORMAT, unit="count", label_size=9.5, gap_width=80)
        blocks.append(chart)
        fact_ids += [it.fact_id for it in chart.bar_items()]
    group, chans, ents, cells = panels[0]
    items = []
    for c in chans:
        others = [(e, cells[(e, c)]) for e in ents if e != brand.name and (e, c) in cells]
        it = vs_top(ctx, brand.name, cells.get((brand.name, c)), others, "count", "많은",
                    [N(labels[c]), T(" 문서 수")])
        if it:
            items.append(it)
            fact_ids += [p.fact_id for p in it[1] if p.type == "fact"]
    lead = lead_block([P(N(brand.name), T(" vs 경쟁사 — 블로그·카페·뉴스 검색 결과 문서 수(누적)"))])
    blocks = [
        title_block("Search", "채널별 언급량 비교"), lead, *blocks, *insight_blocks(items[:3]),
        footnote(ctx, fact_ids, [T("네이버 검색 결과 문서 수(누적) — 검색한 사람 수가 아닌 글 수")]),
    ]
    return SlideSpec(slide_id="MN1", template_id="mention_compare.v1", page_role="content", section_id="search",
                     title="채널별 언급량 비교", blocks=_decorate(ctx, blocks), needs_review=True, is_data=True)


# ---------------------------------------------------------------- BL1 블로그 문서 유형 (P3-3)

BLOG_TYPES = [("real_use", "실사용", "navy"), ("sponsored", "협찬", "red"), ("shopping_affiliate", "쇼핑·제휴", "gold"),
              ("promo_template", "홍보 템플릿", "line_other"), ("other", "기타", "bar_other")]
BLOG_TYPE_HELP = [("실사용", "직접 사서 써 본 후기"), ("협찬", "제품·원고료를 받았다고 밝힌 글"),
                  ("쇼핑·제휴", "구매 링크·수수료 안내가 중심인 글"), ("홍보 템플릿", "같은 문구가 반복되는 홍보 글"),
                  ("기타", "정보·뉴스 정리 등")]
BLOG_MAX_ROWS = 8


def blog_type_page(ctx: QuantContext, exclude: frozenset[str] = frozenset(), min_n: int = 20) -> Optional[SlideSpec]:
    """BL1: 검색어(브랜드, 브랜드+제품군; 자사 먼저, 경쟁사 다음)마다 블로그 상위 글의 유형 비중 누적 막대.
    표본(n)이 min_n 미만인 검색어는 빼고, 자사 검색어가 하나도 없으면 만들지 않는다."""
    brand = single_brand(ctx)
    if brand is None:
        return None
    entities = _entities(brand, exclude)
    by_kw: dict[str, dict] = defaultdict(dict)
    owner: dict[str, str] = {}
    for f in facts_of(ctx, "blog_type_share", brand.id):
        kw = f.dims.get("keyword") or f.entity
        if f.entity in entities and int(f.dims.get("n", 0)) >= min_n:
            by_kw[kw].setdefault(f.dims.get("type"), f)
            owner.setdefault(kw, f.entity)
    rows = [kw for kw in by_kw if len(by_kw[kw]) >= 2]
    rows.sort(key=lambda kw: (entities.index(owner[kw]), kw != owner[kw], kw))
    rows = rows[:BLOG_MAX_ROWS]
    if not any(owner[kw] == brand.name for kw in rows):
        return None
    types = [(t, label, color) for t, label, color in BLOG_TYPES if any(t in by_kw[kw] for kw in rows)]
    series = [BarSeries(name=label, color=color, items=[bar_item(ctx, owner[kw], kw, by_kw[kw][t], "share")
                                                        if t in by_kw[kw] else None for kw in rows])
              for t, label, color in types]
    body = region("body")
    chart_w = body.w * 0.70
    reg = Region(x=body.x, y=body.y, w=chart_w, h=min(body.h, 40 * len(rows) + 40))
    chart = BarChartBlock(block_id="chart", region=reg, categories=rows, series=series, stacked=True,
                          number_format='0"%"', unit="percent", label_size=10, gap_width=45)
    fact_ids = [it.fact_id for it in chart.bar_items()]
    hx, hw = body.x + chart_w + 24, body.w - chart_w - 24
    help_paras = [P(N(name, bold=True), T(f" — {desc}")) for name, desc in BLOG_TYPE_HELP
                  if name in {label for _, label, _ in types}]
    blocks: list[Block] = [
        ShapeBlock(block_id="help_bg", region=Region(x=hx, y=body.y, w=hw, h=36 + 22 * len(help_paras)), fill="tint"),
        text("help_head", Region(x=hx + 12, y=body.y + 6, w=hw - 24, h=20), [T("유형 기준")], color="navy", weight="semibold"),
        text_block("help", "body", Region(x=hx + 12, y=body.y + 30, w=hw - 24, h=22 * len(help_paras)), help_paras,
                   spec="card_body", size=9.5, line=16),
        chart,
    ]
    items = []
    for kw in rows[:3]:
        parts: list[Part] = []
        for t, label, _ in BLOG_TYPES[:2]:  # 실사용 · 협찬
            if t in by_kw[kw]:
                parts += ([T(" · ")] if parts else []) + [T(f"{label} "), ctx.pf.fact(by_kw[kw][t], "share", bold=t == "real_use")]
        if parts:
            items.append(([N(kw)], parts))
            fact_ids += [p.fact_id for p in parts if p.type == "fact"]
    shown = [f for kw in rows for f in by_kw[kw].values()]
    lead = lead_block([P(N(brand.name), T(" 블로그 상위 글은 어떤 글인가 — 실사용 후기·협찬·쇼핑 제휴 비중"))])
    blocks = [
        title_block("Customer", "블로그 문서 유형"), lead, *blocks, *insight_blocks(items),
        footnote(ctx, fact_ids, [T("네이버 블로그 정확도순 상위 글을 AI가 유형별로 분류")], sample_note(shown, "검색어별")),
    ]
    return SlideSpec(slide_id="BL1", template_id="blog_type.v1", page_role="content", section_id="voc",
                     title="블로그 문서 유형", blocks=_decorate(ctx, blocks), needs_review=True, is_data=True)
