"""Case and appendix templates: C1 case_card (2·3·4 columns), M1 market_evidence,
A-source (PRD 11; QUALITY_BASELINE p.54/68/104).

Cards need an accepted image and at least one accepted Claim. Numbers on cards come only
from manual/collected Facts linked to the material; plain digits in claim text are left
for QC to block rather than silently passed.
"""
from __future__ import annotations

import math
import re
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

from core.composition.chrome import (
    D, L, N, P, PartFactory, T, circled, footnote_block, lead_block, takeaway_block, text_block, title_block,
)
from core.composition.formatters import UNIT_FORMATTER
from core.composition.measure import PX_PER_PT, height_at, line_count, text_width
from core.composition.tokens import region, type_spec
from core.metrics.registry import FactRegistry
from core.schemas.materials import CaseMaterial, ClaimRef, SourceRef
from core.schemas.slidespec import (
    Block, ImageBlock, Paragraph, Part, Region, ShapeBlock, SlideSpec, TableBlock, TableCell, TableColumn, TableRow,
)

METRIC_LABELS = {"views": "조회", "likes": "좋아요", "comments": "댓글", "followers": "팔로워", "count": "건수",
                 "amount_krw": "금액", "percent": "비율", "rank": "순위"}

CARD_GEOMETRY = {  # columns -> (card width, gap, image max height)
    2: (560, 40, 236),
    3: (384, 24, 200),
    4: (282, 24, 150),
}
CARD_TOP, CARD_BOTTOM = 140, 652  # v6 body: under the headline, above the footer rule


def eligible_case(m: CaseMaterial) -> Optional[str]:
    """None if usable for a case card, else the reason it is not."""
    if m.review_status != "accepted":
        return "자료 미채택"
    if not m.asset or m.asset.review_status != "accepted":
        return "채택된 이미지 없음"
    if not [c for c in m.claims if c.review_status == "accepted"]:
        return "채택된 근거 문장 없음"
    return None


def _claim_parts(claim: ClaimRef, pf: PartFactory) -> list[Part]:
    """Fact parts are re-formatted from the registry; stored display strings are never trusted."""
    out = []
    for p in claim.parts:
        if p.type == "fact" and p.fact_id:
            if p.fact_id in pf.registry:
                out.append(pf.fact(p.fact_id, p.formatter or "int", bold=p.bold))
            else:  # left for QC to block as FACT_UNLINKED
                out.append(p.model_copy(update={"display": p.display or "?"}))
        else:
            out.append(p.model_copy())
    return out


def _claim_paragraph(claim: ClaimRef, pf: PartFactory, bullet: str, color: Optional[str], bold: bool) -> Paragraph:
    return Paragraph(parts=_claim_parts(claim, pf), bullet=bullet, color=color, bold=bold)


def _metric_lines(m: CaseMaterial, pf: PartFactory) -> list[Paragraph]:
    parts_per_metric: list[list[Part]] = []
    for fid in m.metric_fact_ids:
        fact = pf.registry.get(fid)
        if fact is None or getattr(fact, "verification_status", "eligible") != "eligible":
            continue
        label = getattr(fact, "label", None) or METRIC_LABELS.get(fact.metric, fact.metric)
        formatter = UNIT_FORMATTER.get(fact.unit, "int")
        # The label is a name (e.g. a product "제프리3"), never a figure; the figure is the bound fact.
        parts_per_metric.append([N(label), T(" "), pf.fact(fid, formatter, bold=False)])
    lines = []
    for i in range(0, len(parts_per_metric), 2):
        chunk = parts_per_metric[i:i + 2]
        parts: list[Part] = []
        for j, ps in enumerate(chunk):
            if j:
                parts.append(T(" · "))
            parts += ps
        lines.append(Paragraph(parts=parts, bullet="┃"))
    return lines


def _card_label(m: CaseMaterial) -> str:
    if m.label:
        return m.label
    name = m.event_name or _clean_title(m.title, m.entity)
    return f"{m.entity} · {name}" if m.entity else name


def _clean_title(title: str, entity: Optional[str]) -> str:
    """Headline -> activity name: drop a leading quote, bracket tags, the outlet suffix and the brand prefix."""
    t = re.sub(r"^\s*[“\"'‘][^”\"'’]{1,60}[”\"'’]\s*[…·,:\-]*\s*", "", title)
    t = re.sub(r"\[[^\]]{1,20}\]\s*", "", t)
    t = re.split(r"\s+[-|:]\s+", t)[0]
    if entity:
        t = re.sub(rf"^{re.escape(entity)}\s*[,·:]?\s*", "", t)
    return t.strip() or title


def _link_line(m: CaseMaterial, width: float) -> Paragraph:
    """One line: ▲ title · date. A long headline is shortened; the full title is in the source table."""
    size = type_spec("card_body")["size"]
    day = m.activity_date or m.source.published_at  # an article without an activity date shows its publish date
    tail = ""
    if day:
        tail = " · 0000.00.00" + ("~0000.00.00" if m.activity_date_end and m.activity_date_end != day else "")
    title = _fit_one_line(m.title, width - text_width("▲ " + tail, size) - 12, size)
    title_part = L(title, m.source.url) if m.source.url else N(title)
    parts = [title_part]
    if day:
        parts += [T(" · "), D(day)]
        if m.activity_date_end and m.activity_date_end != day:
            parts += [T("~"), D(m.activity_date_end)]
    return Paragraph(parts=parts, bullet="▲", color="link")


def _fit_one_line(text: str, width: float, size_pt: float) -> str:
    """Shorten a card header to one line; the full title stays in the card's source link."""
    if text_width(text, size_pt) <= width:
        return text
    while text and text_width(text + "…", size_pt) > width:
        text = text[:-1]
    return text.rstrip(" ·,") + "…"


def _cell_height(paragraphs: list[Paragraph], width: float, size: float) -> float:
    lines = sum(line_count([((p.bullet + " ") if p.bullet else "", p.bold)] + [(x.rendered(), x.bold or p.bold) for x in p.parts],
                           width, size) for p in paragraphs)
    return lines * size * 1.4 * 96 / 72


def _height(paragraphs: list[Paragraph], width: float, spec: str) -> float:
    ts = type_spec(spec)
    lines = 0
    extra = 0.0
    for p in paragraphs:
        runs = [(p.plain(), p.bold)]
        lines += line_count(runs, width, ts["size"])
        extra += p.space_before
    return (lines * ts["line"] + extra) * PX_PER_PT


def _card_blocks(i: int, m: CaseMaterial, x: float, w: float, img_max_h: float, pf: PartFactory) -> tuple[list[Block], float]:
    """Blocks for one card; returns (blocks, content bottom y). The frame is sized by the page."""
    blocks: list[Block] = []
    frame = Region(x=x, y=CARD_TOP + 14, w=w, h=CARD_BOTTOM - CARD_TOP - 14)
    blocks.append(ShapeBlock(block_id=f"card{i}_frame", region=frame, line="panel_border", fill="white"))
    label_text = _fit_one_line(_card_label(m), w - 64, 11)
    label_w = min(w - 40, 40 + text_width(label_text, 11) * 1.05)
    label = Region(x=x + (w - label_w) / 2, y=CARD_TOP, w=label_w, h=28)
    blocks.append(ShapeBlock(block_id=f"card{i}_label_bg", region=label, fill="card_label"))
    blocks.append(text_block(f"card{i}_label", "panel_header", label, [P(N(label_text))], spec="card_label",
                             align="c", valign="m"))
    inner_x, inner_w = x + 18, w - 36
    img_h = min(img_max_h, inner_w * 9 / 16)
    img = Region(x=inner_x, y=CARD_TOP + 46, w=inner_w, h=img_h)
    blocks.append(ImageBlock(block_id=f"card{i}_image", region=img, asset_id=m.asset.id, crop=m.asset.crop))
    y = img.y + img.h + 8

    sections: list[tuple[str, list[Paragraph], str, Optional[str], bool]] = [
        ("link", [_link_line(m, inner_w)], "c", None, False),
        ("metrics", _metric_lines(m, pf), "l", None, False),
        ("desc", [_claim_paragraph(c, pf, "▸", "subtle", False) for c in m.claims
                  if c.review_status == "accepted" and c.kind == "fact"], "l", "subtle", False),
        ("impl", [_claim_paragraph(c, pf, "→", "navy", True) for c in m.claims
                  if c.review_status == "accepted" and c.kind != "fact"], "l", "navy", True),
    ]
    for key, paras, align, color, bold in sections:
        if not paras:
            continue
        h = _height(paras, inner_w, "card_body")
        blocks.append(text_block(f"card{i}_{key}", "body", Region(x=inner_x, y=y, w=inner_w, h=h), paras,
                                 spec="card_body", align=align, color=color or "text", bold=bold,
                                 editable=key in ("desc", "impl")))
        y += h + 8
    return blocks, y


def case_pages(materials: list[CaseMaterial], pf: PartFactory, *, title_main: str, title_sub: str, slide_prefix: str,
               lead_for: Callable[[list[CaseMaterial]], list[Paragraph]], badge: list[Block]) -> list[SlideSpec]:
    cards = [m for m in materials if eligible_case(m) is None]
    if not cards:
        return []
    per_page = 4  # cards arrive in report order (build._case_order)
    while True:
        pages_n = math.ceil(len(cards) / per_page)
        size = math.ceil(len(cards) / pages_n)
        chunks = [cards[i:i + size] for i in range(0, len(cards), size)]
        built = [_case_page(chunk, pf) for chunk in chunks]
        # Over-dense cards: fewer columns per page, i.e. split onto more pages (QUALITY_BASELINE p.68).
        if all(fits for _, fits in built) or per_page == 2:
            break
        per_page -= 1
    slides = []
    for idx, ((blocks, _), chunk) in enumerate(zip(built, chunks)):
        sources = _source_footnote(chunk) + _measured_parts(chunk, pf)
        slide_id = slide_prefix + (f"-p{idx + 1}" if idx else "")
        all_blocks = [title_block(title_main, title_sub), lead_block(lead_for(chunk)), *blocks,
                      footnote_block([P(*sources)]), *badge]
        slides.append(SlideSpec(
            slide_id=slide_id, template_id=f"case_card_{len(chunk)}col.v1", page_role="content", section_id="campaign",
            title=title_sub, blocks=all_blocks, asset_ids=[m.asset.id for m in chunk if m.asset],
            source_ids=[m.source.id for m in chunk], parent_slide_id=slide_prefix if idx else None,
            needs_review=True, is_data=True))
    return slides


SPOTLIGHT_INSIGHT_TYPE = (13.5, 20.0)  # size pt, line pt — bigger than the grid card's reading size


def case_spotlight_page(m: CaseMaterial, pf: PartFactory, *, title_main: str, title_sub: str, slide_id: str,
                        badge: list[Block]) -> Optional[SlideSpec]:
    """One full slide for a person-picked case: a large image, the activity period, and its
    claims as a numbered insight list. The grid in `case_pages` fits many cases per slide
    (QUALITY_BASELINE p54/p68); this is the one-case-per-slide deep dive a person opts a
    case into instead, so it never changes the grid's existing card count."""
    if eligible_case(m) is not None:
        return None
    avail_h = CARD_BOTTOM - CARD_TOP
    img_w = 640
    img = Region(x=40, y=CARD_TOP, w=img_w, h=avail_h)  # fills the full column height, no letterboxed gap
    blocks: list[Block] = [ImageBlock(block_id="spot_image", region=img, asset_id=m.asset.id, crop=m.asset.crop)]

    col_x, col_w = img.x + img.w + 40, 1240 - (img.x + img.w + 40)
    insight_claims = [c for c in m.claims if c.review_status == "accepted"]
    # Thin content reads as more lines scaled up, not a half-empty column: fewer insights -> bigger type.
    size, line = (16.0, 24.0) if len(insight_claims) <= 2 else SPOTLIGHT_INSIGHT_TYPE
    insights = [Paragraph(parts=_claim_parts(c, pf), bullet=circled(i)) for i, c in enumerate(insight_claims)]
    metrics = _metric_lines(m, pf)
    period = _period_line(m)
    link = _link_line(m, col_w)

    parts_h: list[tuple[str, str, object, float, dict]] = []
    if period:
        parts_h.append(("spot_period", "panel_header", [period], _height([period], col_w, "card_label"), {"spec": "card_label", "color": "subtle"}))
    parts_h.append(("spot_link", "body", [link], _height([link], col_w, "card_body"), {"spec": "card_body"}))
    if insights:
        parts_h.append(("spot_insights", "body", insights, height_at(insights, col_w, size, line), {"spec": "card_body", "size": size, "line": line, "editable": True}))
    if metrics:
        parts_h.append(("spot_metrics", "body", metrics, height_at(metrics, col_w, 13, 19), {"spec": "card_body", "size": 13, "line": 19}))

    gap = 28
    total = sum(h for _, _, _, h, _ in parts_h) + gap * max(0, len(parts_h) - 1)
    y = CARD_TOP + max(0, (avail_h - total) / 2)  # center sparse content instead of leaving the bottom empty
    for block_id, role, paras, h, kw in parts_h:
        blocks.append(text_block(block_id, role, Region(x=col_x, y=y, w=col_w, h=h), paras, **kw))
        y += h + gap

    sources = _source_footnote([m]) + _measured_parts([m], pf)
    sub = f"{m.entity} 핵심 사례" if m.entity else title_sub
    all_blocks = [title_block(title_main, sub), lead_block([P(N(_card_label(m)))]), *blocks,
                 footnote_block([P(*sources)]), *badge]
    return SlideSpec(slide_id=slide_id, template_id="case_spotlight.v1", page_role="content", section_id="campaign",
                     title=sub, blocks=all_blocks, asset_ids=[m.asset.id], source_ids=[m.source.id],
                     needs_review=True, is_data=True)


def _period_line(m: CaseMaterial) -> Optional[Paragraph]:
    start = m.activity_date or m.source.published_at
    if not start:
        return None
    parts: list[Part] = [T("기간 "), D(start)]
    if m.activity_date_end and m.activity_date_end != start:
        parts += [T(" ~ "), D(m.activity_date_end)]
    return P(*parts)


def _case_page(chunk: list[CaseMaterial], pf: PartFactory) -> tuple[list[Block], bool]:
    n = max(2, len(chunk))
    w, gap, img_h = CARD_GEOMETRY[n]
    total = len(chunk) * w + (len(chunk) - 1) * gap
    x0 = 640 - total / 2
    blocks: list[Block] = []
    bottoms = []
    for i, m in enumerate(chunk):
        b, bottom = _card_blocks(i, m, x0 + i * (w + gap), w, img_h, pf)
        blocks += b
        bottoms.append(bottom)
    content_bottom = max(bottoms) + 10
    fits = content_bottom <= CARD_BOTTOM
    for b in blocks:  # all frames share the tallest card's height
        if isinstance(b, ShapeBlock) and b.block_id.endswith("_frame"):
            b.region.h = min(CARD_BOTTOM, content_bottom) - b.region.y
    return blocks, fits


def _measured_parts(chunk: list[CaseMaterial], pf: PartFactory) -> list[Part]:
    """'지표 측정 YYYY.MM.DD' for the card metrics shown on this page (observation dates)."""
    dates = sorted({f.measured_at for m in chunk for fid in m.metric_fact_ids
                    if (f := pf.registry.get(fid)) is not None and getattr(f, "verification_status", "") == "eligible"})
    if not dates:
        return []
    parts: list[Part] = [T(" · 지표 측정 "), D(dates[0])]
    if len(dates) > 1:
        parts += [T("~"), D(dates[-1])]
    return parts


def _domain(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host


def _source_footnote(chunk: list[CaseMaterial]) -> list[Part]:
    parts: list[Part] = [T("*")]
    seen = []
    for m in chunk:
        name = _publisher(m)
        key = (name, m.source.published_at)
        if key in seen:
            continue
        seen.append(key)
        if len(seen) > 1:
            parts.append(T(" · "))
        parts.append(N(name))
        if m.source.published_at:
            parts += [T(" "), D(m.source.published_at)]
    parts.append(T(" · 성과 수치는 각 카드 자료의 관측값"))
    return parts


# ---------------------------------------------------------------- C2 (v6 CASE detail: one case per page)

def _publisher(m: CaseMaterial) -> str:
    """Outlet name for captions: og:site_name is sometimes a keyword list ('브랜드, 프랜차이즈, …')."""
    raw = m.source.publisher or _domain(m.source.url) or m.source.title
    return re.split(r"\s*[,|]\s*", raw)[0].strip() or raw


def _fit_lines(text: str, width: float, size_pt: float, max_lines: int) -> str:
    """Shorten text so it wraps into at most max_lines (adds an ellipsis when cut)."""
    if line_count([(text, False)], width, size_pt) <= max_lines:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_count([(text[:mid].rstrip() + "…", False)], width, size_pt) <= max_lines:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip(" ,·") + "…"


def _section_head(block_id: str, x: float, y: float, w: float, label: str, note: Optional[str] = None) -> list[Block]:
    out: list[Block] = [text_block(block_id, "panel_header", Region(x=x, y=y, w=w, h=20), [P(T(label))],
                                   spec="panel_header", color="navy", valign="b")]
    if note:
        out.append(text_block(f"{block_id}_note", "caption", Region(x=x + 140, y=y + 2, w=w - 140, h=17), [P(T(note))],
                              spec="caption", color="muted", align="r", valign="b", size=8, line=11, weight="light"))
    out.append(ShapeBlock(block_id=f"{block_id}_rule", region=Region(x=x, y=y + 23, w=w, h=0), shape="line",
                          line="navy", line_width=1.0))
    return out


def case_detail_pages(materials: list[CaseMaterial], pf: PartFactory, badge: list[Block], prefix: str = "C2") -> list[SlideSpec]:
    """v6 'CASE' page per accepted case: big image left; summary box, key figure, 진행 방식 and verbatim
    source excerpts right. Everything shown is an accepted claim, a confirmed fact or a verbatim quote."""
    pages: list[SlideSpec] = []
    ok = [m for m in materials if not eligible_case(m)]
    for n, m in enumerate(ok, start=1):
        facts_claims = [c for c in m.claims if c.review_status == "accepted" and c.kind == "fact"]
        interp = [c for c in m.claims if c.review_status == "accepted" and c.kind != "fact"]
        metric_ids = [fid for fid in m.metric_fact_ids
                      if getattr(pf.registry.get(fid), "verification_status", "eligible") == "eligible"]
        day = m.activity_date or m.source.published_at
        blocks: list[Block] = [title_block("Campaign", sub_parts=[N(m.entity or ""), T("  ·  사례 상세")])]
        if day:
            span = [D(day)] + ([T(" – "), D(m.activity_date_end)] if m.activity_date_end and m.activity_date_end != day else [])
            blocks.append(text_block("meta", "meta", region("meta"), [P(T("기간  "), *span)], spec="meta", align="r",
                                     valign="m", color="navy"))
        blocks.append(text_block("case_kicker", "caption", Region(x=48, y=61, w=1184, h=21), [P(N(_card_label(m)))],
                                 spec="panel_header", color="muted"))
        head = interp[0] if interp else facts_claims[0]
        # P4 사례 카드 해설이 채택돼 있으면(경쟁사·벤치마크 사례만 해당) 그 쪽이 리드로 우선한다 —
        # 원문 그대로의 claim보다 '무엇을 했고 왜 통했나'로 다듬은 문장이 낫다.
        lead_parts = [T(m.ai_detail)] if m.ai_detail else _claim_parts(head, pf)
        l_size, l_line = (19, 25) if height_at([P(*lead_parts)], 1184, 19, 25) <= 50 else (15, 20)
        blocks.append(text_block("lead", "lead", Region(x=48, y=84, w=1184, h=50), [P(*lead_parts)],
                                 spec="lead", color="navy", size=l_size, line=l_line, editable=True))
        # left: the image with its source caption
        img = Region(x=48, y=146, w=560, h=315)
        blocks.append(ImageBlock(block_id="case_image", region=img, asset_id=m.asset.id, crop=m.asset.crop))
        pub = _publisher(m)
        cap = [N(pub)] + ([T(" · "), D(m.source.published_at)] if m.source.published_at else []) + [T(" 원문 이미지")]
        blocks.append(text_block("case_image_cap", "caption", Region(x=48, y=464, w=560, h=14), [P(*cap)],
                                 spec="caption", color="muted", size=6.5, line=9, weight="light"))
        blocks.append(text_block("case_link", "caption", Region(x=48, y=482, w=560, h=16), [_link_line(m, 560)],
                                 spec="card_body", align="l", size=8.5, line=12))
        # right top: navy summary box + key figure tile
        rx, rw = 640, 592
        summary = [P(T("성과 요약", weight="semibold", color="white"))]
        bullets = ([P(N(getattr(pf.registry.get(fid), "label", None) or "수치"), T(" "),
                      pf.fact(fid, UNIT_FORMATTER.get(pf.registry.get(fid).unit, "int"), bold=True, color="white"),
                      bullet="▲") for fid in metric_ids[:3]]
                   or [P(*_claim_parts(c, pf), bullet="▲") for c in facts_claims[:3]])
        # The box holds what fits; every claim still appears in full under 진행 방식 below.
        while len(bullets) > 1 and height_at(summary + bullets, 372, 8.5, 13) > 84:
            bullets = bullets[:-1]
        s_size, s_line = (8.5, 13) if height_at(summary + bullets, 372, 8.5, 13) <= 84 else (7.5, 11)
        blocks.append(ShapeBlock(block_id="summary_bg", region=Region(x=rx, y=146, w=400, h=96), fill="navy"))
        blocks.append(text_block("summary", "body", Region(x=rx + 16, y=154, w=372, h=84), summary + bullets,
                                 spec="card_body", color="summary_text", size=s_size, line=s_line))
        tile = Region(x=rx + 410, y=146, w=rw - 410, h=96)
        blocks.append(ShapeBlock(block_id="figure_bg", region=tile, fill="tint"))
        inner = Region(x=tile.x + 12, y=tile.y + 10, w=tile.w - 24, h=tile.h - 20)
        if metric_ids:
            fid = metric_ids[0]
            label = getattr(pf.registry.get(fid), "label", None) or "핵심 수치"
            blocks.append(text_block("figure_label", "body", Region(x=inner.x, y=inner.y, w=inner.w, h=34),
                                     [P(N(_fit_lines(label, inner.w, 9, 2)))], spec="card_body", size=9, line=13,
                                     weight="semibold"))
            fig = [P(pf.fact(fid, UNIT_FORMATTER.get(pf.registry.get(fid).unit, "int"), color="navy"))]
            f_size = next((sz for sz in (20, 16, 13, 11) if height_at(fig, inner.w, sz, sz * 1.3) <= 34), 11)
            blocks.append(text_block("figure", "body", Region(x=inner.x, y=inner.y + 38, w=inner.w, h=34), fig,
                                     spec="card_body", size=f_size, line=round(f_size * 1.3, 1), weight="heavy", valign="b"))
        else:
            blocks.append(text_block("figure_label", "body", Region(x=inner.x, y=inner.y, w=inner.w, h=18), [P(T("발행처"))],
                                     spec="card_body", size=9, line=13, color="muted"))
            blocks.append(text_block("figure", "body", Region(x=inner.x, y=inner.y + 22, w=inner.w, h=inner.h - 22),
                                     [P(N(_fit_lines(pub, inner.w, 12, 2)))], spec="card_body", size=12, line=17,
                                     weight="bold", color="navy"))
        # right middle: 진행 방식 (accepted fact claims)
        y = 258
        blocks += _section_head("how_head", rx, y, rw, "진행 방식")
        y += 31
        for i, c in enumerate(facts_claims[:4]):
            para = P(*_claim_parts(c, pf), bullet="·")
            h = max(18, _height([para], rw, "card_body"))
            blocks.append(text_block(f"how{i}", "body", Region(x=rx, y=y, w=rw, h=h), [para], spec="card_body",
                                     editable=True))
            y += h + 6
        # right bottom: verbatim excerpts (the AI candidates' source sentences)
        quotes = list(dict.fromkeys(c.quote for c in facts_claims + interp if c.quote))[:3]
        if quotes and y < 560:
            y += 8
            blocks += _section_head("quote_head", rx, y, rw, "원문 근거", note="원문 발췌")
            y += 31
            for i, q in enumerate(quotes):
                if y > 610:
                    break
                text = _fit_lines(f"“{q}”", rw - 17, 9.5, 2)
                paras = [P(Part(type="quote", text=text)), P(N(pub), color="muted")]
                h = _height(paras, rw - 17, "card_body")  # QC measures every line at the block size
                blocks.append(ShapeBlock(block_id=f"quote{i}_dot", region=Region(x=rx, y=y + 5, w=8, h=8), fill="green"))
                blocks.append(text_block(f"quote{i}", "body", Region(x=rx + 17, y=y, w=rw - 17, h=h + 2), paras,
                                         spec="card_body", line=14))
                blocks[-1].paragraphs[1].parts[0].size = 7
                y += h + 8
        # bottom: P4 시사점(있으면 우선) or the remaining interpretation as the summary line
        if m.ai_implication:
            blocks.append(takeaway_block(P(T(m.ai_implication))))
        elif len(interp) > 1 or (interp and head is not interp[0]):
            rest = interp[1] if head is interp[0] else interp[0]
            blocks.append(takeaway_block(P(*_claim_parts(rest, pf))))
        foot = [T("*출처  "), N(pub)]
        if m.source.published_at:
            foot += [T(" "), D(m.source.published_at)]
        elif m.activity_date:  # no publish date (e.g. a social post): the activity period dates the page
            foot += [T(" · 활동 "), D(m.activity_date)]
            if m.activity_date_end and m.activity_date_end != m.activity_date:
                foot += [T("~"), D(m.activity_date_end)]
        foot += [T(" · 문장은 채택된 근거, 수치는 원문과 대조해 확인한 값")]
        blocks.append(footnote_block([P(*foot)]))
        blocks += badge
        pages.append(SlideSpec(slide_id=f"{prefix}-{n}", template_id="case_detail.v1", page_role="content",
                               section_id="campaign", brand_id=m.brand_id, title=_card_label(m),
                               blocks=blocks, asset_ids=[m.asset.id], source_ids=[m.source.id], needs_review=False,
                               is_data=True))
    return pages


# ---------------------------------------------------------------- M1

MARKET_INSIGHT_TYPE = (12.5, 18.0)  # size pt, line pt


def market_page(materials: list[CaseMaterial], pf: PartFactory, badge: list[Block]) -> Optional[SlideSpec]:
    pages = market_pages(materials, pf, badge)
    return pages[0] if pages else None


def market_pages(materials: list[CaseMaterial], pf: PartFactory, badge: list[Block]) -> list[SlideSpec]:
    """M1 market evidence, continued on as many pages as the accepted rows need (none is dropped)."""
    rows_src = [m for m in materials if m.review_status == "accepted"
                and [c for c in m.claims if c.review_status == "accepted"]]
    if not rows_src:
        return []
    columns = [TableColumn(key="item", label="항목", width=0.22), TableColumn(key="body", label="내용", width=0.53, align="l"),
               TableColumn(key="src", label="출처", width=0.25)]
    built = []
    for m in rows_src:
        paras = [Paragraph(parts=_claim_parts(c, pf), bullet="▸" if c.kind == "fact" else "→",
                           color=None if c.kind == "fact" else "navy", bold=c.kind != "fact")
                 for c in m.claims if c.review_status == "accepted"]
        metric = _metric_lines(m, pf)
        src = [N(_publisher(m))]
        if m.source.published_at:
            src += [T(" "), D(m.source.published_at)]
        cells = [TableCell(paragraphs=[P(N(m.title))]), TableCell(paragraphs=paras + metric, align="l"),
                 TableCell(paragraphs=[P(*src)])]
        h = max(_cell_height(cell.paragraphs, 1184 * col.width - 12, 10) for col, cell in zip(columns, cells))
        built.append((m, TableRow(cells=cells, ref=m.id), max(52, math.ceil(h + 10))))
    # Greedy pages: the table may use the body down to the footnote; the first page keeps room for insights.
    limit_first, limit_next = 380, 470
    chunks, cur, used = [], [], 0
    for item in built:  # rows share one height (the tallest), so a page holds len × max
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
        table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=table_h), columns=columns,
                           rows=[r[1] for r in chunk], row_height=row_h, header_height=32, size=10, header_size=10)
        sub = "시장·타겟 근거"
        sub_parts = [T(sub)]
        if len(chunks) > 1:
            sub_parts += [T(" "), Part(type="meta", key="page", text=f"({i + 1}/{len(chunks)})")]
        lead = lead_block([P(T("시장·타겟 근거 요약 — 공식 자료·보고서의 확인된 사실 중심"))])
        blocks = [title_block("Market", sub_parts=sub_parts), lead, table]
        shown = [r[0] for r in chunk]
        insights = _market_insights(shown, pf) if i == 0 else []
        if insights:
            size, line = MARKET_INSIGHT_TYPE
            y = 196 + table_h + 16
            h = height_at(insights, 1160, size, line)
            if y + h <= 640:  # only when the whole summary fits; a clipped one reads as an error
                blocks.append(text_block("insights", "body", Region(x=60, y=y, w=1160, h=h), insights, spec="card_body",
                                         size=size, line=line, editable=True))
        blocks += [footnote_block([P(*_market_footnote(shown))]), *badge]
        slides.append(SlideSpec(slide_id="M1" + (f"-p{i + 1}" if i else ""), template_id="market_evidence.v1",
                                page_role="content", section_id="campaign", title=sub, blocks=blocks,
                                source_ids=[m.source.id for m in shown], needs_review=True, is_data=True,
                                parent_slide_id="M1" if i else None))
    return slides


def _market_insights(rows: list[CaseMaterial], pf: PartFactory) -> list[Paragraph]:
    """Up to 3 numbered takeaways, one per row, preferring its interpretation claim over
    the plain fact (the ①②③ 'how to read this' pattern used in the reference deck)."""
    out = []
    for m in rows[:3]:
        claims = [c for c in m.claims if c.review_status == "accepted"]
        pick = next((c for c in claims if c.kind != "fact"), claims[0] if claims else None)
        if pick is None:
            continue
        parts = [N(m.title), T(" — ")] + _claim_parts(pick, pf)
        out.append(Paragraph(parts=parts, bullet=circled(len(out)), bold=pick.kind != "fact",
                             color="navy" if pick.kind != "fact" else None))
    return out


def _market_footnote(rows_src: list[CaseMaterial]) -> list[Part]:
    dates = sorted(d for d in (m.source.published_at or m.activity_date for m in rows_src) if d)
    parts: list[Part] = [T("*각 행 출처 기준")]
    if dates:
        parts += [T(" · 발행 "), D(dates[0])]
        if dates[-1] != dates[0]:
            parts += [T("~"), D(dates[-1])]
    return parts + [T(" · 서로 다른 정의의 수치는 한 축으로 합치지 않음")]


# ---------------------------------------------------------------- A-source

def source_pages(sources: list[tuple[SourceRef, str]], badge: list[Block]) -> list[SlideSpec]:
    """sources: (SourceRef, used_in label). Rows split by measured height, never by shrinking text."""
    if not sources:
        return []
    columns = [TableColumn(key="name", label="자료", width=0.30, align="l"), TableColumn(key="date", label="일자", width=0.12),
               TableColumn(key="url", label="출처(URL)", width=0.58, align="l")]
    size = type_spec("table")["size"]
    url_w = 1184 * 0.58 - 16
    rows: list[tuple[TableRow, float]] = []
    for src, used_in in sources:
        # Readable, one-line URL text (Korean paths are percent-encoded); the link keeps the full address.
        url_text = _fit_one_line(unquote(src.url or "").replace("https://", "").replace("http://", ""), url_w - 8, size)
        lines = max(1, line_count([(src.title, False)], 1184 * 0.30 - 16, size))
        h = 14 + lines * 14
        url_part = L(url_text, src.url) if src.url else (N(src.publisher) if src.publisher else T("업로드 자료"))
        date_part = D(src.published_at) if src.published_at else (D(src.fetched_at.date()) if src.fetched_at else T("—"))
        rows.append((TableRow(cells=[TableCell(paragraphs=[P(N(src.title))]), TableCell(paragraphs=[P(date_part)]),
                                     TableCell(paragraphs=[P(url_part)])], ref=src.id), h))
    pages: list[list[tuple[TableRow, float]]] = [[]]
    budget = 652 - 131 - 30
    # The renderer draws every row at the page's tallest row height, so paginate on that, not on the sum.
    for row, h in rows:
        tallest = max([h] + [x for _, x in pages[-1]])
        if pages[-1] and (tallest * (len(pages[-1]) + 1) > budget or len(pages[-1]) >= 12):
            pages.append([])
        pages[-1].append((row, h))
    slides = []
    for i, chunk in enumerate(pages):
        row_h = max(h for _, h in chunk)
        table_h = 30 + row_h * len(chunk)
        table = TableBlock(block_id="table", region=Region(x=48, y=131, w=1184, h=table_h), columns=columns,
                           rows=[r for r, _ in chunk], row_height=row_h, header_height=30, size=size, header_size=size)
        sub = "사용 자료 출처"
        sub_parts = [T(sub)]
        if len(pages) > 1:
            sub_parts += [T(" "), Part(type="meta", key="page", text=f"({i + 1}/{len(pages)})")]
        blocks = [title_block("Appendix", sub_parts=sub_parts),
                  lead_block([P(T("본문 사례·근거별 출처 — 링크는 원문으로 연결"))]), table,
                  footnote_block([P(T("*수치 원장은 factbook.csv, 이미지 원장은 assets.csv에 별도 제공"))]), *badge]
        slides.append(SlideSpec(slide_id="A-source" + (f"-p{i + 1}" if i else ""), template_id="source_table.v1",
                                page_role="appendix", section_id="appendix", title=sub, blocks=blocks,
                                source_ids=[r.ref for r, _ in chunk if r.ref], parent_slide_id="A-source" if i else None))
    return slides
