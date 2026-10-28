"""01. 마케팅 Overview templates (02_보고서_표준목차_장표명세.md §01).

Only 1-1 (브랜드 × 카테고리 × 타겟 매핑) is implemented: it is the one slide in this chapter
buildable purely from Project config, with no new collector. The rest of the chapter needs
data this product does not collect yet:
- 1-2 (카테고리 인지 설문), 1-5 일부: survey/브랜드 트래커 자료 — no ingestion path (M10).
- 1-3: 네이버 데이터랩 쇼핑인사이트 + 무신사 '전체' 탭 랭킹 — different API/scraper than the
  검색어트렌드 client this product has (see integrations/naver/client.py); not built.
- 1-4: 무신사·29CM 리뷰 수·순위 — no commerce-ranking collector (M4).
- 1-6: 고객 분기 리포트 교차검증 — no internal-report ingestion (M9).
"""
from __future__ import annotations

import math
from typing import Optional

from core.composition.cases import _cell_height, _fit_one_line
from core.composition.chrome import N, P, PERIOD, T, footnote_block, lead_block, title_block
from core.composition.quant import QuantContext
from core.schemas.materials import TARGET_SEGMENTS, CaseMaterial
from core.schemas.project import Project
from core.schemas.slidespec import Paragraph, Region, SlideSpec, TableBlock, TableCell, TableColumn, TableRow

ROW_H = 60
HEADER_H = 32


def brand_mapping_page(ctx: QuantContext) -> Optional[SlideSpec]:
    """1-1: 브랜드 × 카테고리 × 타겟 매핑. 대표 제품·가격대와 기간 내 주요 활동(내부 리포트)은
    이 제품에 아직 입력 경로가 없어 열에서 뺀다 — 없는 값을 채워 보여주지 않는다."""
    brands = ctx.project.brands
    if not brands:
        return None
    columns = [
        TableColumn(key="brand", label="브랜드", width=0.14),
        TableColumn(key="category", label="주력 카테고리", width=0.18, align="l"),
        TableColumn(key="target", label="핵심 타겟", width=0.24, align="l"),
        TableColumn(key="rivals", label="카테고리 경쟁 세트", width=0.30, align="l"),
        TableColumn(key="note", label="비고", width=0.14, align="l"),
    ]
    rows = []
    for b in brands:
        cat = b.categories[0] if b.categories else "미등록"
        target = b.target.label if b.target else "미등록"
        rivals = ", ".join(b.competitors) if b.competitors else "미등록"
        cells = [
            TableCell(paragraphs=[P(N(b.name))]),
            TableCell(paragraphs=[P(N(cat))], align="l"),
            TableCell(paragraphs=[P(N(target))], align="l"),
            TableCell(paragraphs=[P(N(rivals))], align="l"),
            TableCell(paragraphs=[P(T("대표 제품·가격대, 기간 내 활동(내부)은 자료 등록 후 반영"))], align="l"),
        ]
        rows.append(TableRow(cells=cells, ref=b.id))
    table_h = HEADER_H + ROW_H * len(rows)
    table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=table_h), columns=columns, rows=rows,
                       row_height=ROW_H, header_height=HEADER_H, size=11, header_size=11)
    lead = lead_block([P(T("브랜드별 경쟁 단위 확정 — 이후 모든 장표는 이 표의 카테고리 경쟁 세트 기준으로만 비교"))])
    blocks = [
        title_block("Brand Status", "브랜드 × 카테고리 × 타겟 매핑"),
        lead, table,
        footnote_block([P(PERIOD(ctx.project.period.start, ctx.project.period.end),
                          T(" 기준 설정값 · 출처: 프로젝트 설정(브랜드·카테고리·타겟·경쟁 세트) · "
                            "대표 제품·가격대와 기간 내 주요 활동(내부)은 자료 등록 후 별도 업데이트"))]),
    ]
    return SlideSpec(slide_id="1-1", template_id="brand_mapping.v1", page_role="content", section_id="overview",
                     title="브랜드 × 카테고리 × 타겟 매핑", blocks=blocks, needs_review=False, is_data=True)


MAX_PER_CELL = 2


def campaign_matrix_page(project: Project, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    """1-6: 타겟·채널별 캠페인 매트릭스. 스펙은 고객 분기 리포트 교차검증을 전제로 하지만 이 제품은
    아직 내부 리포트를 읽지 못한다(M9 파서 없음) — 그래서 모든 셀은 공개 수집 자료 기준이고, 스펙이
    정한 대로 전부 [외부]로 표시한다. target_segment는 리서치 추출 단계(app/services/research.py
    EXTRACT_SCHEMA)에서 원문에 타겟이 뚜렷이 드러날 때만 AI가 붙이는 태그이며, 자료가 먼저 '캠페인
    사례'로 채택된 뒤에만 이 표에 들어온다. '키 타겟' 칸 강조(gold)는 하지 않는다: Brand.target은
    나이 하나로 표현되는데, TARGET_SEGMENTS 중 '직장인'·'외국인 관광객'·'팝업·OOH·PR'은 나이로
    가를 수 없어 억지로 매핑하면 틀린 칸을 강조하게 된다."""
    self_brand = {b.id: b.name for b in project.brands}
    campaign = [m for m in materials if m.section_id == "campaign" and m.review_status == "accepted"
               and m.target_segment in TARGET_SEGMENTS and m.brand_id in self_brand and m.entity == self_brand[m.brand_id]]
    if not campaign:
        return None
    brands = project.brands
    col_w = round(0.84 / len(brands), 4)
    columns = [TableColumn(key="segment", label="타겟", width=0.16)] + \
              [TableColumn(key=b.id, label=b.name, width=col_w, align="l") for b in brands]

    def cell_paras(items: list[CaseMaterial], width: float) -> list[Paragraph]:
        if not items:
            return [P(T("—", color="muted"))]
        out = []
        for m in items[:MAX_PER_CELL]:
            name = _fit_one_line(m.event_name or m.title, width - 12, 10)
            out.append(P(T("[외부] ", color="muted"), N(name)))
        if len(items) > MAX_PER_CELL:
            out.append(P(T(f"외 {len(items) - MAX_PER_CELL}건", color="muted")))
        return out

    counts: dict[str, int] = {seg: 0 for seg in TARGET_SEGMENTS}
    rows = []
    for seg in TARGET_SEGMENTS:
        row_items = [m for m in campaign if m.target_segment == seg]
        counts[seg] = len(row_items)
        cells = [TableCell(paragraphs=[P(N(seg))])]
        cell_h = 0.0
        for b in brands:
            paras = cell_paras([m for m in row_items if m.brand_id == b.id], 1184 * col_w)
            cells.append(TableCell(paragraphs=paras, align="l"))
            cell_h = max(cell_h, _cell_height(paras, 1184 * col_w - 12, 10))
        rows.append((TableRow(cells=cells), cell_h))

    # TableBlock has one row_height for all rows: use the tallest. Uniform rows stay simple and
    # this matrix only ever has 6 rows, never enough for that to waste noticeable space.
    row_h = max(max(ROW_H, math.ceil(h + 14)) for _, h in rows)
    table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=HEADER_H + row_h * len(rows)),
                       columns=columns, rows=[r for r, _ in rows], row_height=row_h, header_height=HEADER_H,
                       size=10, header_size=10)

    top = max(counts, key=lambda s: counts[s]) if any(counts.values()) else None
    empty = [s for s in TARGET_SEGMENTS if counts[s] == 0]
    if top is None:
        lead_parts = [T("수집된 캠페인 사례 중 타겟이 분류된 건이 아직 없음 — 사례 채택 후 반영")]
    else:
        lead_parts = [T("집중: "), N(top), T(" / 부족: "),
                     N("·".join(empty)) if empty else T("전 구간에서 사례 확보")]
    lead = lead_block([P(*lead_parts)])
    blocks = [
        title_block("Brand Status", "타겟·채널별 캠페인 매트릭스"),
        lead, table,
        footnote_block([P(PERIOD(project.period.start, project.period.end),
                          T(" · [외부] 공개 수집 자료 기준(내부 분기 리포트 교차검증 미연동) · "
                            "타겟은 원문에 명시된 경우만 AI가 분류 · 미분류 사례는 제외"))]),
    ]
    return SlideSpec(slide_id="1-6", template_id="campaign_matrix.v1", page_role="content", section_id="overview",
                     title="타겟·채널별 캠페인 매트릭스", blocks=blocks, needs_review=True, is_data=True)
