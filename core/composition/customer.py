"""05. 소비자 분석(customer) templates — Phase 1-3 소비자 원문(VOC).

5-1(소비자 인식 원문)·5-2(브랜드 인식 경로)만 구현했다. 둘 다 run_voc_item이 모은 같은 소비자 원문을
읽는다 — 캠페인 사례와 달리 글 하나하나가 독립된 증언이라 '같은 활동 묶기'는 하지 않는다. 체험단·협찬
글(voc_sponsored)과 감성·주제가 분류되지 않은 글(AI 분류 실패)은 집계에서 뺀다.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core.composition.cases import _cell_height, _fit_lines, _publisher
from core.composition.chrome import D, M, N, P, T, circled, footnote_block, lead_block, text_block, title_block
from core.schemas.materials import CaseMaterial
from core.schemas.slidespec import Block, Region, SlideSpec, TableBlock, TableCell, TableColumn, TableRow

TOPIC_LABEL = {"price": "가격", "quality": "품질", "design": "디자인", "shipping": "배송", "cs": "AS", "other": "기타"}
AWARENESS_LABEL = {"ad": "광고", "referral": "지인 추천", "influencer": "인플루언서·SNS", "store": "매장",
                   "search": "검색", "other": "기타"}
SENTIMENT_LABEL = {"positive": "긍정", "negative": "부정", "neutral": "중립"}
BODY_X, BODY_W, BODY_TOP = 48, 1184, 131
MAX_QUOTES_PER_SENTIMENT = 5


def _usable(materials: list[CaseMaterial]) -> list[CaseMaterial]:
    """Accepted, classified, not a sponsored/experience-group post — the pool both slides read."""
    return [m for m in materials if m.section_id == "voc" and m.review_status == "accepted"
            and not m.voc_sponsored and m.voc_sentiment]


def _footnote_common(rows: list[CaseMaterial], extra: str) -> list:
    dates = sorted(d for d in (m.source.published_at or m.activity_date for m in rows) if d)
    parts = [T("*표본 "), M(str(len(rows)), "count"), T("건 · AI가 원문을 읽어 분류(체험단·협찬 제외)")]
    if dates:
        parts += [T(" · 수집 "), D(dates[0])]
        if dates[-1] != dates[0]:
            parts += [T("~"), D(dates[-1])]
    return parts + [T(f" · {extra}")] if extra else parts


def _newest_first(m: CaseMaterial) -> tuple:
    """Sort key: dated quotes by date, undated ones after them (by id) — never compare a date with a str."""
    d = m.source.published_at or m.activity_date
    return (d is not None, d or date.min, m.id)


def voc_summary_page(project, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    """5-1: 긍정·부정 각 최대 5건의 원문 요약 + 불만 요인 TOP3."""
    rows = _usable(materials)
    if not rows:
        return None
    pos = sorted([m for m in rows if m.voc_sentiment == "positive"],
                key=_newest_first, reverse=True)[:MAX_QUOTES_PER_SENTIMENT]
    neg = sorted([m for m in rows if m.voc_sentiment == "negative"],
                key=_newest_first, reverse=True)[:MAX_QUOTES_PER_SENTIMENT]
    if not pos and not neg:
        return None

    def quote_row(m: CaseMaterial) -> TableRow:
        src = [N(_publisher(m))]
        if m.source.published_at:
            src += [T(" "), D(m.source.published_at)]
        body_w = BODY_W * 0.58 - 12
        cells = [TableCell(paragraphs=[P(N(SENTIMENT_LABEL.get(m.voc_sentiment, "")))]),
                TableCell(paragraphs=[P(T(_fit_lines(m.event_name or m.title, body_w, 10, 2)))], align="l"),
                TableCell(paragraphs=[P(*src)])]
        return TableRow(cells=cells, ref=m.id)

    columns = [TableColumn(key="sentiment", label="구분", width=0.12),
              TableColumn(key="body", label="원문 요약", width=0.58, align="l"),
              TableColumn(key="src", label="출처", width=0.30)]
    table_rows = [quote_row(m) for m in [*pos, *neg]]
    row_h = 40
    table_h = 32 + row_h * len(table_rows)
    table = TableBlock(block_id="table", region=Region(x=BODY_X, y=BODY_TOP, w=BODY_W, h=table_h), columns=columns,
                       rows=table_rows, row_height=row_h, header_height=32, size=10, header_size=10)

    neg_topics: dict[str, int] = {}
    for m in neg:
        neg_topics[m.voc_topic] = neg_topics.get(m.voc_topic, 0) + 1
    top_complaints = sorted(neg_topics.items(), key=lambda kv: kv[1], reverse=True)[:3]
    blocks: list[Block] = [
        title_block("Customer", "소비자 인식 원문"),
        lead_block([P(T(f"{project.brands[0].name} 소비자 원문 "), M(str(len(rows)), "count"), T("건 — 긍정 "),
                     M(str(len(pos)), "count"), T("건 · 부정 "), M(str(len(neg)), "count"), T("건"))]),
        table,
    ]
    if top_complaints:
        y = BODY_TOP + table_h + 16
        items = [P(N(TOPIC_LABEL.get(topic, "기타")), T(" "), M(f"({n}건)", "count"), bullet=circled(i))
                for i, (topic, n) in enumerate(top_complaints)]
        blocks.append(text_block("complaints", "body", Region(x=BODY_X, y=y, w=BODY_W, h=60), items, spec="card_body"))
    blocks.append(footnote_block([P(*_footnote_common(rows, ""))]))
    return SlideSpec(slide_id="5-1", template_id="voc_summary.v1", page_role="content", section_id="voc",
                     title="소비자 인식 원문", blocks=blocks, source_ids=[m.source.id for m in [*pos, *neg]],
                     needs_review=True, is_data=True)


def awareness_channel_page(project, materials: list[CaseMaterial]) -> Optional[SlideSpec]:
    """5-2: 소비자가 브랜드를 처음 알거나 확인한 경로 비중."""
    rows = [m for m in _usable(materials) if m.voc_awareness]
    if not rows:
        return None
    counts: dict[str, int] = {}
    for m in rows:
        counts[m.voc_awareness] = counts.get(m.voc_awareness, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    total = len(rows)
    columns = [TableColumn(key="channel", label="경로", width=0.35, align="l"),
              TableColumn(key="count", label="건수", width=0.25),
              TableColumn(key="pct", label="비중", width=0.40)]
    table_rows = []
    for channel, n in ranked:
        pct = round(n / total * 100)
        table_rows.append(TableRow(cells=[
            TableCell(paragraphs=[P(N(AWARENESS_LABEL.get(channel, "기타")))], align="l"),
            TableCell(paragraphs=[P(M(str(n), "count"), T("건"))]),
            TableCell(paragraphs=[P(M(f"{pct}%", "percent"))]),
        ], ref=channel))
    row_h = 40
    table_h = 32 + row_h * len(table_rows)
    table = TableBlock(block_id="table", region=Region(x=BODY_X, y=BODY_TOP, w=BODY_W, h=table_h), columns=columns,
                       rows=table_rows, row_height=row_h, header_height=32, size=11, header_size=11)
    top = AWARENESS_LABEL.get(ranked[0][0], "기타")
    blocks: list[Block] = [
        title_block("Customer", "브랜드 인식 경로"),
        lead_block([P(T(f"{project.brands[0].name} 소비자가 가장 많이 꼽은 경로 — "), N(top))]),
        table,
        footnote_block([P(*_footnote_common(rows, "경로가 원문에 드러난 글만 집계"))]),
    ]
    return SlideSpec(slide_id="5-2", template_id="awareness_channel.v1", page_role="content", section_id="voc",
                     title="브랜드 인식 경로", blocks=blocks, source_ids=[m.source.id for m in rows],
                     needs_review=True, is_data=True)
