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
