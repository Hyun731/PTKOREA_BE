"""Phase 2 커머스 리뷰 — CM1(자사 판매·리뷰 자산), CM2(경쟁사 리뷰 비교) (02_보고서_표준목차_장표명세.md §2-9).

한 행 = 플랫폼 하나 + 정확한 상품(SKU) 하나(app/services/commerce.py의 group_key() 단위) — 여러 스냅샷을
합치거나 평균 내지 않는다. 체험단·협찬 리뷰는 수집 단계에서 이미 키워드 집계에서 빠졌다. 자사 브랜드끼리
평점을 나란히 비교하는 문장은 core/quality/qc.py의 기존 규칙(3b)이 막는다 — 여기서 새로 막을 것은 없다.
"""
from __future__ import annotations

import math
from typing import Optional

from core.composition.cases import _cell_height, _fit_lines
from core.composition.chrome import D, M, N, P, T, footnote_block, lead_block, title_block
from core.schemas.materials import ReviewKeywordRef, ReviewSnapshotRef
from core.schemas.slidespec import Block, Paragraph, Part, Region, SlideSpec, TableBlock, TableCell, TableColumn, TableRow

PLATFORM_LABEL = {"musinsa": "무신사", "29cm": "29CM", "oliveyoung": "올리브영", "smartstore": "스마트스토어", "coupang": "쿠팡"}


def _rating_parts(s: ReviewSnapshotRef) -> list[Part]:
    if s.access_status != "ok":
        return [T(s.reason or "접근 불가", color="muted")]
    if s.rating is None or not s.review_count:
        return [T("평점 미확보", color="muted")]
    return [N(f"{s.rating:g}/{s.rating_scale:g}"), T(" ("), M(f"{s.review_count:,}건", "count"), T(")")]


def _keyword_cell(keywords: list[ReviewKeywordRef], sentiment: str, width: float, limit: int = 2) -> list[Paragraph]:
    rows = sorted((k for k in keywords if k.review_status == "accepted" and k.sentiment == sentiment),
                  key=lambda k: -k.sample_size)[:limit]
    if not rows:
        return [P(T("채택된 키워드 없음", color="muted"))]
    paras: list[Paragraph] = []
    for k in rows:
        head = [N(k.keyword), T(" ("), M(f"{k.sample_size}건", "count"), T(")")]
        if sentiment == "negative" and k.blocks_purchase:
            head += [T(" · "), T("구매 방해", bold=True, color="red")]
        paras.append(P(*head, bullet="▸"))
        if k.quotes:
            q = k.quotes[0]
            quote_text = _fit_lines(f"“{q['text']}”", max(width, 60), 9, 2)
            paras.append(P(Part(type="quote", text=quote_text)))
            if q.get("posted_at"):
                paras.append(P(D(q["posted_at"]), color="muted"))
    return paras


def _table_page(slide_id: str, title_sub: str, lead: Paragraph, columns: list[TableColumn],
                rows: list[tuple[ReviewSnapshotRef, TableRow]], foot: list[Part]) -> list[SlideSpec]:
    """Rows share one page while they fit the body; later rows continue on the next page (never clipped)."""
    sized: list[tuple[ReviewSnapshotRef, TableRow, float]] = []
    for s, row in rows:
        h = max(_cell_height(c.paragraphs, 1184 * col.width - 12, 9.5) for col, c in zip(columns, row.cells))
        sized.append((s, row, max(56, math.ceil(h + 12))))
    limit_first, limit_next = 420, 470
    chunks: list[list[tuple[ReviewSnapshotRef, TableRow, float]]] = []
    cur: list[tuple[ReviewSnapshotRef, TableRow, float]] = []
    used = 0
    for item in sized:
        limit = limit_first if not chunks else limit_next
        if cur and max(used, item[2]) * (len(cur) + 1) > limit:
            chunks.append(cur)
            cur, used = [], 0
        cur.append(item)
        used = max(used, item[2])
    if cur:
        chunks.append(cur)
    slides = []
    for i, chunk in enumerate(chunks):
        row_h = max(r[2] for r in chunk)
        table_h = 32 + row_h * len(chunk)
        table = TableBlock(block_id="table", region=Region(x=48, y=148, w=1184, h=table_h), columns=columns,
                           rows=[r[1] for r in chunk], row_height=row_h, header_height=32, size=9.5, header_size=10)
        sub_parts = [T(title_sub)]
        if len(chunks) > 1:
            sub_parts += [T(" "), Part(type="meta", key="page", text=f"({i + 1}/{len(chunks)})")]
        blocks: list[Block] = [title_block("Commerce", sub_parts=sub_parts), lead_block([lead]), table,
                               footnote_block([P(*foot)])]
        slides.append(SlideSpec(slide_id=slide_id + (f"-p{i + 1}" if i else ""), template_id="commerce_review.v1",
                                page_role="content", section_id="commerce_review", title=title_sub, blocks=blocks,
                                source_ids=[], needs_review=True, is_data=True,
                                parent_slide_id=slide_id if i else None))
    return slides


def review_asset_page(snapshots: list[ReviewSnapshotRef], self_name: Optional[str]) -> list[SlideSpec]:
    """CM1 판매·리뷰 자산: 자사 대표 상품의 플랫폼별 평점·리뷰 수, 긍정·부정 키워드(원문 근거)."""
    rows_src = [s for s in snapshots if s.role == "self" and s.review_status == "accepted"]
    if not rows_src:
        return []
    rows_src.sort(key=lambda s: (PLATFORM_LABEL.get(s.platform, s.platform), s.product_name))
    columns = [TableColumn(key="platform", label="플랫폼·상품", width=0.18),
              TableColumn(key="rating", label="평점(리뷰 수)", width=0.16),
              TableColumn(key="pos", label="긍정 키워드", width=0.33, align="l"),
              TableColumn(key="neg", label="부정 키워드", width=0.33, align="l")]
    rows: list[tuple[ReviewSnapshotRef, TableRow]] = []
    for s in rows_src:
        cells = [TableCell(paragraphs=[P(N(PLATFORM_LABEL.get(s.platform, s.platform))), P(N(s.product_name), color="muted")]),
                 TableCell(paragraphs=[P(*_rating_parts(s))]),
                 TableCell(paragraphs=_keyword_cell(s.keywords, "positive", 1184 * 0.33 - 12), align="l"),
                 TableCell(paragraphs=_keyword_cell(s.keywords, "negative", 1184 * 0.33 - 12), align="l")]
        rows.append((s, TableRow(cells=cells, ref=s.id)))
    lead = P(N(self_name or "자사"), T(" 대표 상품의 판매 플랫폼 공개 리뷰 — 체험단·협찬 리뷰는 키워드 집계에서 제외"))
    dates = sorted({s.measured_at for s in rows_src})
    foot = [T("*측정 시점 "), D(dates[0])]
    if dates[-1] != dates[0]:
        foot += [T("~"), D(dates[-1])]
    foot.append(T(" · 체험단·협찬 리뷰는 별도 집계, 키워드 표본에서 제외"))
    return _table_page("CM1", "판매·리뷰 자산", lead, columns, rows, foot)


def competitor_review_page(snapshots: list[ReviewSnapshotRef]) -> list[SlideSpec]:
    """CM2 경쟁사 리뷰 비교: 경쟁사 대표 상품의 평점·리뷰 불만 — 공략할 경쟁 약점으로 본다."""
    rows_src = [s for s in snapshots if s.role == "competitor" and s.review_status == "accepted"]
    if not rows_src:
        return []
    rows_src.sort(key=lambda s: (s.entity, PLATFORM_LABEL.get(s.platform, s.platform), s.product_name))
    columns = [TableColumn(key="who", label="경쟁사", width=0.16),
              TableColumn(key="platform", label="플랫폼·상품", width=0.22),
              TableColumn(key="rating", label="평점(리뷰 수)", width=0.16),
              TableColumn(key="neg", label="부정 키워드(약점)", width=0.46, align="l")]
    rows: list[tuple[ReviewSnapshotRef, TableRow]] = []
    for s in rows_src:
        cells = [TableCell(paragraphs=[P(N(s.entity))]),
                 TableCell(paragraphs=[P(N(PLATFORM_LABEL.get(s.platform, s.platform))), P(N(s.product_name), color="muted")]),
                 TableCell(paragraphs=[P(*_rating_parts(s))]),
                 TableCell(paragraphs=_keyword_cell(s.keywords, "negative", 1184 * 0.46 - 12), align="l")]
        rows.append((s, TableRow(cells=cells, ref=s.id)))
    lead = P(T("경쟁사 베스트셀러 리뷰의 반복 불만 — 공략 가능한 경쟁 약점"))
    dates = sorted({s.measured_at for s in rows_src})
    foot = [T("*측정 시점 "), D(dates[0])]
    if dates[-1] != dates[0]:
        foot += [T("~"), D(dates[-1])]
    foot.append(T(" · 자사 대비 비교 문장은 쓰지 않음(경쟁사 간 불만만 나열)"))
    return _table_page("CM2", "경쟁사 리뷰 비교", lead, columns, rows, foot)


# ---------------------------------------------------------------- CR1 커머스 경쟁 지표(판매 순위·후기·찜)

AGE_BAND_LABEL = {"AGE_BAND_ALL": "전체", "AGE_BAND_MINOR": "19세 이하", "AGE_BAND_20": "20~24세",
                  "AGE_BAND_25": "25~29세", "AGE_BAND_30": "30~34세", "AGE_BAND_35": "35~39세",
                  "AGE_BAND_40": "40세 이상"}
AGE_BAND_ORDER = list(AGE_BAND_LABEL)
CR_MAX_ENTITIES = 5  # 자사 + 경쟁사 4


def _rank_cell(ctx, best, count) -> TableCell:
    from core.composition.chrome import P as _P
    if best is None:
        if count is None:
            return TableCell(paragraphs=[_P(T("-", color="muted"))])
        return TableCell(paragraphs=[_P(M("100위 밖", "rank_out", color="muted"))])
    return TableCell(paragraphs=[_P(ctx.pf.fact(best, "rank", bold=True), T("  "), M("100위 안", "rank_scope"), T(" "),
                                    ctx.pf.fact(count, "int", bold=False), T("개", color="muted"))])


def market_rank_page(ctx) -> Optional[SlideSpec]:
    """CR1: 자사와 경쟁사를 같은 잣대로 — 무신사 카테고리 월간 판매 순위(전체·키 타겟 연령대)와 브랜드 최다
    후기 상품의 후기·찜 수. 자사 행·막대를 강조하고, 순위 격차를 아래 KPI 상자로 보인다."""
    from core.composition.chrome import headline_blocks
    from core.composition.compare import bar_item, facts_of, latest_by, single_brand, text
    from core.composition.quant import _decorate, _panel_header
    from core.composition.tokens import region
    from core.schemas.slidespec import BarChartBlock, ShapeBlock

    brand = single_brand(ctx)
    if brand is None:
        return None
    entities = [brand.name, *brand.competitors][:CR_MAX_ENTITIES]
    counts = facts_of(ctx, "commerce_ranked_items", brand.id, platform="musinsa")
    bests = facts_of(ctx, "commerce_best_rank", brand.id, platform="musinsa")
    cats = list(dict.fromkeys((f.dims["category"], f.dims.get("category_label", "")) for f in counts))
    cnt = latest_by(counts, lambda f: (f.entity, f.dims["category"], f.dims["age_band"]))
    best = latest_by(bests, lambda f: (f.entity, f.dims["category"], f.dims["age_band"]))
    reviews = latest_by(facts_of(ctx, "commerce_top_reviews", brand.id, platform="musinsa"), lambda f: f.entity)
    likes = latest_by(facts_of(ctx, "commerce_top_likes", brand.id, platform="musinsa"), lambda f: f.entity)
    # 순위표가 비교가 되려면 자사 + 경쟁사 한 곳 이상이 같은 판에 있어야 한다
    cats = [c for c in cats if sum(1 for e in entities if (e, c[0], "AGE_BAND_ALL") in cnt) >= 2][:2]
    if not cats and len([e for e in entities if e in reviews]) < 2:
        return None

    body = region("body")
    left_w = body.w * 0.58 if reviews else body.w
    blocks: list[Block] = []
    fact_ids: list[str] = []
    y = body.y
    kpis: list[tuple[str, object, str, object, str]] = []  # (라벨, 경쟁사 fact, 경쟁사명, 자사 fact|None, 자사명)
    # 표 하나 = 머리 44 + 열 머리 30 + 행 36 × 브랜드 수. 두 카테고리가 본문에 다 들어갈 때만 둘 다 싣는다.
    row_h = 36.0
    fits, used = [], 0.0
    for c in cats:
        h = 44 + 30 + row_h * sum(1 for e in entities if (e, c[0], "AGE_BAND_ALL") in cnt) + 12
        if fits and used + h > body.h:
            break
        fits.append(c)
        used += h
    cats = fits
    for ci, (code, label) in enumerate(cats):
        bands = [b for b in AGE_BAND_ORDER if any((e, code, b) in cnt for e in entities)]
        ents = [e for e in entities if (e, code, "AGE_BAND_ALL") in cnt]
        ents.sort(key=lambda e: (e != brand.name, best[(e, code, "AGE_BAND_ALL")].value
                                 if (e, code, "AGE_BAND_ALL") in best else 10 ** 6))
        blocks += _panel_header(f"rank{ci}_header", body.x, y, left_w,
                                [T(f"무신사 {label} 월간 판매 순위 · 연령대별")])
        columns = [TableColumn(key="who", label="브랜드", width=0.28)] + \
                  [TableColumn(key=b, label=AGE_BAND_LABEL[b], width=0.72 / len(bands)) for b in bands]
        rows = []
        for e in ents:
            mine = e == brand.name
            cells = [TableCell(paragraphs=[P(N(e, bold=mine, color="red" if mine else None))],
                               fill="highlight" if mine else None)]
            for b in bands:
                bf, cf = best.get((e, code, b)), cnt.get((e, code, b))
                cell = _rank_cell(ctx, bf, cf)
                if mine:
                    cell.fill = "highlight"
                cells.append(cell)
                fact_ids += [f.id for f in (bf, cf) if f is not None]
            rows.append(TableRow(cells=cells))
        table_h = 30 + row_h * len(rows)
        blocks.append(TableBlock(block_id=f"rank{ci}", region=Region(x=body.x, y=y + 44, w=left_w, h=table_h),
                                 columns=columns, rows=rows, row_height=row_h, header_height=30, size=10,
                                 header_size=9.5))
        y += 44 + table_h + 12
        # KPI: 키 타겟 연령대(없으면 전체)에서 1위 경쟁사 vs 자사
        band = next((b for b in bands if b != "AGE_BAND_ALL"), "AGE_BAND_ALL")
        comp = [(e, best[(e, code, band)]) for e in ents if e != brand.name and (e, code, band) in best]
        if comp:
            ce, cf = min(comp, key=lambda r: r[1].value)
            sf = best.get((brand.name, code, band))
            if sf is None or sf.value > cf.value:
                kpis.append((f"{label} · {AGE_BAND_LABEL[band]}", cf, ce, sf, brand.name))

    if reviews:
        rx, rw = body.x + left_w + 28, body.w - left_w - 28
        ents = [e for e in entities if e in reviews]
        panels = [("rev", "최다 후기 상품 후기 수", reviews)] + ([("like", "그 상품 찜 수", likes)] if likes else [])
        ph = body.h / len(panels)
        for i, (key, title, src) in enumerate(panels):
            py = body.y + i * ph
            blocks += _panel_header(f"{key}_header", rx, py, rw, [T(f"무신사 {title}")])
            items = [bar_item(ctx, e, e, src[e], "count", role="self" if e == brand.name else "other")
                     for e in sorted((e for e in ents if e in src), key=lambda e: -src[e].value)]
            chart = BarChartBlock(block_id=f"{key}_chart", region=Region(x=rx, y=py + 44, w=rw, h=ph - 52),
                                  items=items, number_format='#,##0', unit="count", label_size=10, gap_width=45)
            blocks.append(chart)
            fact_ids += [it.fact_id for it in chart.bar_items()]

    # 아래 KPI 상자: '경쟁사 N위 → 자사 M위(또는 순위 밖)'
    kr = region("insights")
    top_y = region("takeaway").y
    if kpis:
        n = min(3, len(kpis))
        w = (kr.w - 16 * (n - 1)) / n
        for i, (lab, cf, ce, sf, sn) in enumerate(kpis[:n]):
            x = kr.x + i * (w + 16)
            blocks.append(ShapeBlock(block_id=f"kpi{i}_box", region=Region(x=x, y=top_y + 8, w=w, h=110),
                                     shape="rounded", fill="tint", line="panel_border"))
            blocks.append(text(f"kpi{i}_label", Region(x=x + 14, y=top_y + 16, w=w - 28, h=20),
                               [M(lab, "segment", bold=True, color="navy")], size=10))
            parts: list[Part] = [N(ce), T(" "), ctx.pf.fact(cf, "rank", bold=True), T("  →  "), N(sn, color="red"),
                                 T(" ")]
            parts += [ctx.pf.fact(sf, "rank", bold=True)] if sf is not None else [T("순위 밖", bold=True, color="red")]
            blocks.append(text(f"kpi{i}_value", Region(x=x + 14, y=top_y + 42, w=w - 28, h=40), parts, size=15))
            blocks.append(text(f"kpi{i}_note", Region(x=x + 14, y=top_y + 86, w=w - 28, h=24),
                               [T("무신사 월간 판매 순위 · 최고 순위 상품 기준", color="muted")], size=9))
            fact_ids += [f.id for f in (cf, sf) if f is not None]

    # 헤드라인: 가장 큰 순위 격차 하나, 근거 줄은 후기 수
    claim: list[Part]
    if kpis:
        lab, cf, ce, sf, sn = kpis[0]
        claim = [N(brand.name), T(", "), M(lab, "segment"), T(" 판매 순위에서 "), N(ce), T("에 "),
                 T("밀린다", color="accent")]
    else:
        claim = [N(brand.name), T(" 판매 플랫폼 경쟁 지표 — 순위·후기·찜 수 비교")]
    evidence: list[Paragraph] = []
    if kpis:
        lab, cf, ce, sf, sn = kpis[0]
        evidence.append(P(N(ce), T(" "), ctx.pf.fact(cf, "rank"), T(" · "), N(sn), T(" "),
                          *( [ctx.pf.fact(sf, "rank")] if sf is not None else [T("순위 밖")])))
    if reviews and brand.name in reviews:
        others = [(e, f) for e, f in reviews.items() if e != brand.name]
        if others:
            oe, of = max(others, key=lambda r: r[1].value)
            evidence.append(P(T("최다 후기 상품 후기 수 "), N(brand.name), T(" "), ctx.pf.fact(reviews[brand.name], "int"),
                              T("건 · "), N(oe), T(" "), ctx.pf.fact(of, "int"), T("건")))
    head = headline_blocks([P(*claim)], evidence, region("lead"))
    reg = ctx.metrics.registry.facts
    measured = max((reg[f].measured_at for f in fact_ids if f in reg), default=None)
    foot_parts: list[Part] = [T("*"), M("무신사 카테고리 랭킹 '전체' 탭 · 최근 30일(월간) · 성별 전체 · 상위 100위 안 브랜드 최고 순위 "
                                        "상품(100위 안 상품 수 함께)", "method"),
                              T(" · 후기·찜 수 = 브랜드 상품을 후기순으로 정렬한 첫 상품")]
    if measured:
        foot_parts += [T(" · 측정 "), D(measured)]
    foot_parts += [T(" · "), M("무신사 공개 랭킹·상품 목록", "source")]
    foot = footnote_block([P(*foot_parts)])
    blocks = [title_block("Commerce", "판매 순위·후기 경쟁"), *head, *blocks, foot]
    return SlideSpec(slide_id="CR1", template_id="commerce_rank.v1", page_role="content", section_id="commerce_review",
                     title="판매 순위·후기 경쟁", blocks=_decorate(ctx, blocks), needs_review=True, is_data=True)
