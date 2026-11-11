"""자사 vs 경쟁사 비교 장표 (P3-1 OW-CMP).

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
from core.composition.quant import QuantContext, _decorate, _measured
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
    """'댓글 감성 n=24~310 · AI 분류' for derived percent facts (n lives in dims)."""
    ns = sorted({int(f.dims["n"]) for f in facts if footnote_label(f)})
    if not ns:
        return []
    n = f"n={ns[0]}" if len(ns) == 1 else f"n={ns[0]}~{ns[-1]}"
    return [M(f"{what} {n} · AI 분류", "sample")]


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
    row_h = (body.h - head_h - 6 - row_gap * (n - 1)) / n
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
                    chart = _sentiment_chart(ctx, f"row{r}_{key}", reg, ch["sentiment"], label_pt - 0.5)
                    blocks.append(chart)
                    fact_ids += [it.fact_id for it in chart.bar_items()]
                    sent_facts += [f for _, pols in ch["sentiment"] for f in pols.values()]
                    continue
            elif key in ch["kpis"]:
                chart = _kpi_chart(ctx, f"row{r}_{key}", reg, ch["kpis"][key], fmt, brand.name, label_pt)
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
