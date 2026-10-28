"""02. 자사 채널 점검 templates (02_보고서_표준목차_장표명세.md §02).

Only 2-1 (채널 인벤토리) is implemented, and only the columns this product can observe without
judgment: 팔로워·월평균 게시 빈도·반응 수치. 콘텐츠 타겟·톤앤매너·자체/공동 게시 비중처럼 사람의
판단이 필요한 열은 비워 두지 않고 아예 뺐다 — 2-2(운영 공백)·2-3(공동 게시 효율)·2-4(상위
게시물)·2-5(YouTube 성과 상세)·2-6/2-7(자산 전환)·2-9~2-12는 이 제품에 없는 수집기(크리에이터
개별 피드 비교, 네이버 자동완성·블로그, 커뮤니티 6곳)가 전제라 아직 없다.
"""
from __future__ import annotations

from typing import Optional

from core.composition.chrome import M, N, P, T, lead_block, text_block, title_block
from core.composition.formatters import fmt_month_label, fmt_month_range
from core.composition.quant import QuantContext, _footnote, _panel_header, _panel_xs
from core.schemas.facts import Fact
from core.schemas.slidespec import (
    Block, LineChartBlock, LinePoint, LineSeries, Paragraph, Region, SlideSpec, TableBlock, TableCell, TableColumn,
    TableRow,
)


def _find(ctx: QuantContext, brand_id: str, metric: str, **dims: str) -> Optional[Fact]:
    matches = [f for f in ctx.metrics.registry.facts.values()
              if f.brand_id == brand_id and f.metric == metric and all(f.dims.get(k) == v for k, v in dims.items())]
    return max(matches, key=lambda f: f.measured_at) if matches else None


def channel_inventory_page(ctx: QuantContext) -> Optional[SlideSpec]:
    fact_ids: list[str] = []

    def line(label: str, fact: Optional[Fact], formatter: str, suffix: str = "") -> Optional[Paragraph]:
        if fact is None:
            return None
        fact_ids.append(fact.id)
        return P(T(f"{label} "), ctx.pf.fact(fact, formatter, bold=False), T(suffix))

    brand_rows = []
    for b in ctx.project.brands:
        ig = {"followers": _find(ctx, b.id, "owned_followers", channel="instagram"),
             "posts": _find(ctx, b.id, "owned_posts_monthly", channel="instagram"),
             "likes": _find(ctx, b.id, "owned_likes_median", channel="instagram")}
        yt = {"subs": _find(ctx, b.id, "owned_followers", channel="youtube"),
             "videos": _find(ctx, b.id, "owned_videos_monthly", channel="youtube", format="video"),
             "shorts": _find(ctx, b.id, "owned_videos_monthly", channel="youtube", format="shorts"),
             "views_video": _find(ctx, b.id, "owned_views_avg", channel="youtube", format="video"),
             "views_shorts": _find(ctx, b.id, "owned_views_avg", channel="youtube", format="shorts")}
        if not any(ig.values()) and not any(yt.values()):
            continue
        ig_paras = [p for p in [line("팔로워", ig["followers"], "count"), line("월평균 게시물", ig["posts"], "index", "건"),
                                line("중앙값 좋아요", ig["likes"], "count")] if p] or [P(T("미수집", color="muted"))]
        yt_paras = [p for p in [line("구독자", yt["subs"], "count"), line("월평균 동영상", yt["videos"], "index", "건"),
                                line("월평균 쇼츠", yt["shorts"], "index", "건"),
                                line("평균 조회(동영상)", yt["views_video"], "count"),
                                line("평균 조회(쇼츠)", yt["views_shorts"], "count")] if p] or [P(T("미수집", color="muted"))]
        brand_rows.append((b, ig_paras, yt_paras))
    if not brand_rows:
        return None

    columns = [TableColumn(key="brand", label="브랜드", width=0.14),
              TableColumn(key="ig", label="Instagram", width=0.36, align="l"),
              TableColumn(key="yt", label="YouTube", width=0.36, align="l"),
              TableColumn(key="note", label="비고", width=0.14, align="l")]
    rows = []
    max_lines = 1
    for b, ig_paras, yt_paras in brand_rows:
        max_lines = max(max_lines, len(ig_paras), len(yt_paras))
        rows.append(TableRow(cells=[
            TableCell(paragraphs=[P(N(b.name))]),
            TableCell(paragraphs=ig_paras, align="l"),
            TableCell(paragraphs=yt_paras, align="l"),
            TableCell(paragraphs=[P(T("콘텐츠 타겟·톤앤매너·자체/공동 게시 비중은 별도 자료 필요"))], align="l"),
        ], ref=b.id))
    row_h = 24 + max_lines * 19
    table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=32 + row_h * len(rows)),
                       columns=columns, rows=rows, row_height=row_h, header_height=32, size=10, header_size=10)
    lead = lead_block([P(T("공식 계정 기준 팔로워·게시 빈도·반응 — 콘텐츠 타겟·톤앤매너는 판단 자료가 추가로 필요해 비움"))])
    blocks = [
        title_block("Owned", "채널 인벤토리"), lead, table,
        _footnote(ctx, fact_ids, [T("기간 내 공식 계정 전체 게시물 기준(ScrapeCreators) · 비공개·광고 계정은 제외")]),
    ]
    return SlideSpec(slide_id="2-1", template_id="channel_inventory.v1", page_role="content", section_id="owned",
                     title="채널 인벤토리", blocks=blocks, needs_review=True, is_data=True)


def _gap_ranges(months: list[str], gaps: set[str]) -> list[tuple[str, str]]:
    """Consecutive zero-post months collapsed into (start, end) runs."""
    ranges: list[tuple[str, str]] = []
    run_start: Optional[str] = None
    prev: Optional[str] = None
    for m in months:
        if m in gaps:
            run_start = run_start or m
            prev = m
        elif run_start is not None:
            ranges.append((run_start, prev))
            run_start = None
    if run_start is not None:
        ranges.append((run_start, prev))
    return ranges


def operating_gap_page(ctx: QuantContext) -> Optional[SlideSpec]:
    """2-2: 월별 자체 게시 추이에서 공백 구간(자체 게시 0건 달)이 있는 브랜드만 보여준다 — 스펙
    조건 '공백 브랜드가 있을 때'. 자체/공동 게시 구분은 하지 않는다: ScrapeCreators 계정 피드
    응답에 공동 작성자 필드가 없어 어떤 게시물이 크리에이터와의 공동 게시인지 가려낼 수 없다."""
    panels_data = []
    for b in ctx.project.brands:
        by_month = {f.dims["month"]: f for f in ctx.metrics.registry.facts.values()
                   if f.brand_id == b.id and f.metric == "owned_posts_by_month" and f.dims.get("channel") == "instagram"}
        if not by_month:
            continue
        months = sorted(by_month)
        gap_set = {m for m in months if by_month[m].value == 0}
        if not gap_set:
            continue  # spec: this page only exists for a brand that actually has a gap
        panels_data.append((b, months, by_month, _gap_ranges(months, gap_set)))
    if not panels_data:
        return None
    panels_data = panels_data[:3]

    xs, w = _panel_xs(len(panels_data), single=820)
    chart_h = 220
    top = 110
    blocks: list[Block] = []
    fact_ids: list[str] = []
    for i, ((b, months, by_month, ranges), x) in enumerate(zip(panels_data, xs)):
        blocks += _panel_header(f"panel{i}_header", x, top, w, [N(b.name), T(" Instagram 자체 게시 — 월별 건수")])
        points = [LinePoint(month=m, fact_id=by_month[m].id, value=float(by_month[m].value)) for m in months]
        fact_ids += [pt.fact_id for pt in points]
        blocks.append(LineChartBlock(block_id=f"panel{i}_chart", region=Region(x=x, y=top + 44, w=w, h=chart_h),
                                     categories=[fmt_month_label(m) for m in months],
                                     series=[LineSeries(entity=b.name, role="self", points=points)]))
        gap_parts = []
        for j, (s, e) in enumerate(ranges[:2]):
            if j:
                gap_parts.append(T(", "))
            gap_parts.append(M(fmt_month_label(s) if s == e else fmt_month_range(s, e), "month"))
        blocks.append(text_block(f"panel{i}_caption", "caption", Region(x=x, y=top + 44 + chart_h + 6, w=w, h=40),
                                 [P(T("공백 "), *gap_parts, T(" — 자체 게시 없음"))], spec="caption", align="c"))

    lead = lead_block([P(T("자체 게시가 비어 있던 구간 — Owned 피드가 아닌 다른 채널에서만 활동했을 수 있음"))])
    blocks = [
        title_block("Owned", "운영 공백 분석"), lead, *blocks,
        _footnote(ctx, fact_ids, [T("Instagram 공식 계정 자체 게시 기준(ScrapeCreators) · 자체/공동 게시 구분 없음")]),
    ]
    return SlideSpec(slide_id="2-2", template_id="operating_gap.v1", page_role="content", section_id="owned",
                     title="운영 공백 분석", blocks=blocks, needs_review=True, is_data=True)
