"""Deck composer: accepted inputs -> SlidePlan + SlideSpecs (PRD 11, E06, Q02).

Planned slots and generated pages are separate. A slot without data is `needs_input`
until a person supplies data or omits it explicitly; it is never shown to clients as a
skeleton page.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Optional

from core.composition import cases, overview, owned, quant, synthesis
from core.composition.chrome import (
    D, M, N, P, PERIOD, PartFactory, T, chrome_blocks, lead_block, synthetic_badge, text_block, title_block,
)
from core.composition.tokens import region
from core.metrics.engine import MetricsResult, compute
from core.rules.config import RulesConfig
from core.rules.engine import run_rules
from core.schemas.facts import Fact, Finding, Post
from core.schemas.materials import AssetRef, CaseMaterial, OwnedPostRef, SourceRef
from core.schemas.project import Project
from core.schemas.slidespec import (
    BarChartBlock, Binding, DeckSpec, LineChartBlock, Paragraph, Region, ShapeBlock, SlideSpec, SlotPlan, TableBlock,
    TextBlock,
)

# section_id: (number, label, index group, divider subtitle)
SECTIONS: dict[str, tuple[str, str, str, str]] = {
    "overview": ("1", "마케팅 Overview", "Overview", "브랜드 · 카테고리 · 타겟 매핑"),
    "owned": ("2", "자사 채널 점검", "Owned", "채널 인벤토리 · 팔로워 · 게시 빈도"),
    "search": ("2", "검색 경쟁", "Check", "브랜드명 · 카테고리 조합어 · 키 타겟 검색 점유"),
    "influencer": ("3", "인플루언서", "Check", "크리에이터 게시물 관측 지표"),
    "campaign": ("4", "캠페인·시장 사례", "Check", "활동 사실 · 관측 성과 · 근거"),
    "recap": ("5", "Recap", "Insight", "본문 근거 요약"),
    "appendix": ("A", "Appendix", "Appendix", "출처"),
}
TEMPLATE_SECTION = {"1-1": "overview", "1-6": "overview", "2-1": "owned", "2-2": "owned", "2-4": "owned",
                    "2-5": "owned", "2-8a": "search", "2-8b": "search", "2-8c": "search", "2-8d": "search",
                    "3-1": "influencer", "C1": "campaign", "C2": "campaign", "M1": "campaign", "5-recap": "recap",
                    "A-source": "appendix", "ES": "recap", "SWOT": "recap", "NEXT": "recap"}
TEMPLATE_LABEL = {"1-1": "브랜드·카테고리·타겟 매핑", "1-6": "타겟·채널별 캠페인 매트릭스", "2-1": "채널 인벤토리",
                  "2-2": "운영 공백 분석", "2-4": "브랜드별 상위 게시물", "2-5": "YouTube 채널 성과",
                  "2-8a": "브랜드명 검색 점유", "2-8b": "월별 검색 지수", "2-8c": "조합어 검색 점유",
                  "2-8d": "키 타겟 검색 점유", "3-1": "크리에이터 게시물", "C1": "캠페인 사례 카드", "C2": "사례 상세",
                  "M1": "시장·타겟 근거", "5-recap": "Recap", "A-source": "출처 표", "ES": "Executive Summary",
                  "SWOT": "SWOT", "NEXT": "다음 단계 제언"}
SECTION_ORDER = ["overview", "owned", "search", "influencer", "campaign", "recap", "appendix"]
# The deck reads as the 3C table of contents (팩트북 표준 목차): chapter → (number, label, index group, divider text).
# A slide keeps its content section (what it shows, used by checks) and also gets the chapter it sits in.
CHAPTERS: dict[str, tuple[str, str, str, str]] = {
    "exec": ("ES", "Executive Summary", "Summary", "핵심 요약"),
    "company": ("1", "자사 분석", "Company", "자사 채널 · 인플루언서 · 캠페인"),
    "competitor": ("2", "경쟁사 분석", "Competitor", "시장 · 검색 경쟁 · 경쟁사와 벤치마크 사례"),
    "customer": ("3", "소비자 분석", "Customer", "인식 · 구매 여정"),
    "summary": ("4", "종합", "Insight", "3C Recap · SWOT · 다음 단계"),
    "appendix": ("A", "Appendix", "Appendix", "출처"),
}
CHAPTER_ORDER = list(CHAPTERS)
TEMPLATE_CHAPTER = {"1-1": "company", "1-6": "company", "2-1": "company", "2-2": "company", "2-4": "company",
                    "2-5": "company", "3-1": "company", "C1": "company", "C2": "company", "M1": "competitor",
                    "2-8a": "competitor", "2-8b": "competitor", "2-8c": "competitor", "2-8d": "competitor",
                    "5-recap": "summary", "A-source": "appendix", "ES": "exec", "SWOT": "summary", "NEXT": "summary"}
# Order of pages inside the deck; case pages come per group (자사 → 경쟁사 → 벤치마크).
PAGE_ORDER = ["ES", "1-1", "2-1", "2-2", "2-4", "2-5", "3-1", "C1", "C2", "1-6", "M1", "2-8a", "2-8b", "2-8c", "2-8d",
              "C1c", "C2c", "C1b", "C2b", "5-recap", "SWOT", "NEXT", "A-source"]
# (key, role, chapter, card prefix, detail prefix, title_main, title_sub)
CASE_GROUPS = [("self", "company", "C1", "C2", "Campaign", "캠페인 사례"),
               ("competitor", "competitor", "C1c", "C2c", "Competitor", "경쟁사 사례"),
               ("benchmark", "competitor", "C1b", "C2b", "Benchmark", "벤치마크 사례")]
TEMPLATE_ORDER = ["1-1", "1-6", "2-1", "2-2", "2-4", "2-5", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1", "C2", "M1",
                  "5-recap", "A-source"]
FRAME_TEMPLATES = {"cover", "index", "divider", "end"}


@dataclass
class BuildInputs:
    project: Project
    facts: list[Fact]
    posts: list[Post] = field(default_factory=list)
    materials: list[CaseMaterial] = field(default_factory=list)
    owned_posts: list[OwnedPostRef] = field(default_factory=list)
    omitted_slots: dict[str, str] = field(default_factory=dict)  # slot_id -> reason
    lead_overrides: dict[str, list[Paragraph]] = field(default_factory=dict)
    synthesis: dict = field(default_factory=dict)  # ES / SWOT / NEXT text written from the deck (app.services.synthesis)
    generated_on: Optional[date] = None
    deck_id: str = "deck"
    deck_version: int = 1
    config: Optional[RulesConfig] = None


@dataclass
class BuildResult:
    deck: DeckSpec
    metrics: MetricsResult
    findings: list[Finding]
    assets: dict[str, AssetRef]
    sources: dict[str, SourceRef]


def _case_order(project, materials: list) -> list:
    """Report order for cases: a person's explicit order first, then the client's own brand before its
    competitors (in the order the project lists them), each brand's cases by date."""
    rank: dict[str, int] = {}
    for b in project.brands:
        for name in [b.name, *b.competitors, *b.benchmarks]:
            rank.setdefault(name, len(rank))
    return sorted(materials, key=lambda m: (m.order, rank.get(m.entity or "", len(rank)),
                                            str(m.activity_date or m.source.published_at or ""), m.id))


def build_deck(inputs: BuildInputs) -> BuildResult:
    cfg = inputs.config or RulesConfig.load()
    project = inputs.project
    metrics = compute(project, inputs.facts, inputs.posts, cfg)
    findings = run_rules(project, metrics, cfg)
    pf = PartFactory(metrics.registry)
    used_sources = {f.source for f in inputs.facts if f.usable}
    synthetic = "synthetic_fixture" in used_sources
    badge = [synthetic_badge()] if synthetic else []
    accepted = [m for m in inputs.materials if m.review_status == "accepted"]
    infl_assets = {}
    for m in sorted(accepted, key=lambda m: (m.order, m.id)):
        if m.section_id == "influencer" and m.asset and m.asset.review_status == "accepted" and m.brand_id:
            infl_assets.setdefault(m.brand_id, m.asset)
    ctx = quant.QuantContext(project, metrics, findings, pf, cfg, synthetic, infl_assets)

    enabled = set(project.enabled_slides)
    plan: list[SlotPlan] = []
    by_template: dict[str, list[SlideSpec]] = {}

    built: list[tuple[int, int, SlideSpec]] = []  # (page order rank, call order, slide)

    def slot(slot_id: str, template: str, slides: list[SlideSpec], missing_reason: str, brand_id: Optional[str] = None,
             label: Optional[str] = None, chapter: Optional[str] = None, key: Optional[str] = None):
        if slot_id in inputs.omitted_slots:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="omitted",
                                 reason=inputs.omitted_slots[slot_id]))
            return
        if slides:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="ready",
                                 slide_ids=[s.slide_id for s in slides]))
            by_template.setdefault(template, []).extend(slides)
            for s in slides:
                s.chapter = chapter or TEMPLATE_CHAPTER[template]
                built.append((PAGE_ORDER.index(key or template), len(built), s))
        else:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="needs_input",
                                 reason=missing_reason))

    # Order matters: leads are assigned to the first page that can show a finding.
    if "1-1" in enabled:
        s = overview.brand_mapping_page(ctx)
        slot("1-1", "1-1", [s] if s else [], "브랜드 설정 없음")
    if "1-6" in enabled:
        s = overview.campaign_matrix_page(project, inputs.materials)
        slot("1-6", "1-6", [s] if s else [], "타겟이 분류된 채택 캠페인 사례 없음")
    if "2-1" in enabled:
        s = owned.channel_inventory_page(ctx)
        slot("2-1", "2-1", [s] if s else [], "공식 계정 전체 게시물 데이터 없음(Brand.official_profiles 확인)")
    if "2-2" in enabled:
        s = owned.operating_gap_page(ctx)
        slot("2-2", "2-2", [s] if s else [],
             "공백 구간(자체 게시 0건 달) 없음 — 해당 사항 없으면 생략 처리, 2-1 데이터 미확보면 2-1부터 확인")
    if "2-4" in enabled:
        s = owned.top_posts_page(project, inputs.owned_posts)
        slot("2-4", "2-4", [s] if s else [], "이미지가 채택된 상위 게시물 없음")
    if "2-5" in enabled:
        s = owned.youtube_performance_page(ctx)
        slot("2-5", "2-5", [s] if s else [], "YouTube 채널 데이터 없음(Brand.official_profiles 확인)")
    # The search slides put brands side by side in at most 3 panels: more brands continue on the next page.
    groups = _brand_groups(ctx)
    if "2-8a" in enabled:
        pages = [_page_n(s, n) for n, c in groups if (s := quant.search_share(c))]
        slot("2-8a", "2-8a", pages, "12M 브랜드명 검색 세트(자사+경쟁사 전원) 미확보")
    if "2-8b" in enabled:
        pages = [_page_n(s, n) for n, c in groups if (s := quant.search_trend(c))]
        slot("2-8b", "2-8b", pages, "공통 스케일 월별 검색 지수 미확보")
    if "2-8c" in enabled:
        pages = [(n, p) for n, c in groups for p in quant.combo_share_pages(c)]
        if pages:
            for n, p in pages:
                cat = p.slide_id.removeprefix("2-8c-")
                p = _page_n(p, n)
                slot(p.slide_id, "2-8c", [p], "", label=f"조합어 검색 점유 · +{cat}" + (f" ({n})" if n > 1 else ""))
        else:
            slot("2-8c", "2-8c", [], "카테고리 조합어(cat) 검색 세트 미확보")
    if "2-8d" in enabled:
        s = quant.target_table(ctx)
        slot("2-8d", "2-8d", [s] if s else [], "전체·타겟 9M 검색 세트 미확보")
    if "3-1" in enabled:
        for b in project.brands:
            slot(f"3-1-{b.id}", "3-1", quant.creator_pages(ctx, b.id), "기간 내 채택된 creator 게시물 없음", b.id,
                 f"크리에이터 게시물 · {b.name}")
    campaign_ordered = _case_order(project, [m for m in inputs.materials if m.section_id == "campaign"])
    roles = _case_roles(project)
    for role, chapter, card_id, detail_id, title_main, title_sub in CASE_GROUPS:
        campaign = [m for m in campaign_ordered if roles.get(m.entity or "", "self") == role]
        if role != "self" and not campaign and not any(_has_role(project, role)):
            continue  # no benchmark set: no empty benchmark slot either
        what = {"self": "사례", "competitor": "경쟁사 사례", "benchmark": "벤치마크 사례"}[role]
        if "C1" in enabled:
            # Case/market/source pages carry the synthetic badge only if their own facts are synthetic.
            case_badge = badge if _uses_synthetic(campaign, metrics) else []
            # A person-picked case gets its own deep-dive slide instead of a grid card; the rest
            # keep the existing grid untouched (QUALITY_BASELINE p54/p68 pin its exact card count).
            featured = sorted((m for m in campaign if m.featured), key=lambda m: (m.order, m.id))
            grid = [m for m in campaign if not m.featured]
            # With C2 on, featured cases get their full detail page there instead (each case appears once).
            spotlights = [] if "C2" in enabled and featured else [s for i, m in enumerate(featured)
                         if (s := cases.case_spotlight_page(m, pf, title_main=title_main, title_sub=title_sub,
                                                            slide_id=f"{card_id}-spot{i + 1}", badge=case_badge))]
            pages = spotlights + cases.case_pages(grid, pf, title_main=title_main, title_sub=title_sub, slide_prefix=card_id,
                                                  lead_for=_case_lead, badge=case_badge)
            blocked = [f"{m.title}: {cases.eligible_case(m)}" for m in campaign if cases.eligible_case(m)]
            reason = f"채택된 {what} 자료 없음" if not campaign else "사례 카드 조건 미충족 — " + "; ".join(blocked[:3])
            slot(card_id, "C1", pages, reason, label=f"{title_sub} 카드", chapter=chapter, key=card_id)
        if "C2" in enabled:
            detail_cases = campaign
            if "C1" in enabled and any(m.featured for m in campaign):
                detail_cases = [m for m in campaign if m.featured]  # the rest are on the C1 grid
            detail = cases.case_detail_pages(detail_cases, pf, badge if _uses_synthetic(detail_cases, metrics) else [],
                                             prefix=detail_id)
            slot(detail_id, "C2", detail, f"채택된 {what} 자료 없음 (이미지·근거 문장 채택 필요)", label=f"{title_sub} 상세",
                 chapter=chapter, key=detail_id)
    if "M1" in enabled:
        market = [m for m in inputs.materials if m.section_id == "market"]
        slot("M1", "M1", cases.market_pages(market, pf, badge if _uses_synthetic(market, metrics) else []),
             "채택된 시장·타겟 근거 없음")
    if "5-recap" in enabled:
        s = quant.recap(ctx)
        slot("5-recap", "5-recap", [s] if s else [], "요약할 Finding 없음")
    # Written from the other pages on request, so they exist only once written (no empty slot otherwise).
    for key, page in (("ES", synthesis.es_page), ("SWOT", synthesis.swot_page), ("NEXT", synthesis.next_page)):
        part = inputs.synthesis.get(key.lower())
        if part and (s := page(part)):
            slot(key, key, [s], "")
    if "A-source" in enabled:
        srcs = _used_sources(by_template, inputs.materials)
        slot("A-source", "A-source", cases.source_pages(srcs, []), "사용한 출처 없음")

    # Lead overrides (user-fixed sentences) replace the generated lead text only.
    for slides in by_template.values():
        for s in slides:
            if s.slide_id in inputs.lead_overrides:
                for b in s.blocks:
                    if isinstance(b, TextBlock) and b.block_id == "lead":
                        b.paragraphs = [_refresh_facts(p, pf) for p in inputs.lead_overrides[s.slide_id]]
                s.needs_review = False

    ordered = _assemble(project, [s for _, _, s in sorted(built, key=lambda x: (x[0], x[1]))], enabled,
                        inputs.generated_on or date.today(), synthetic)
    for s in ordered:
        s.bindings = _bindings(s, metrics, pf)
        s.notes = _notes(s, metrics)
        if not s.asset_ids:
            s.asset_ids = [b.asset_id for b in s.blocks if getattr(b, "kind", "") == "image"]
    for i, s in enumerate(ordered, start=1):
        s.page_no = i
    assets = {m.asset.id: m.asset for m in inputs.materials if m.asset}
    assets.update({p.asset.id: p.asset for p in inputs.owned_posts if p.asset})
    sources = {m.source.id: m.source for m in inputs.materials}
    deck = DeckSpec(deck_id=inputs.deck_id, deck_version=inputs.deck_version, project_name=project.name,
                    template_version=project.template_version, synthetic_data=synthetic, slides=ordered, plan=plan,
                    input_fingerprint=fingerprint(inputs))
    return BuildResult(deck, metrics, findings, assets, sources)


def _case_roles(project: Project) -> dict[str, str]:
    """Whose case a card is, by its entity: a self brand, a competitor, or a benchmark."""
    roles: dict[str, str] = {}
    for b in project.brands:
        for c in b.competitors:
            roles.setdefault(c, "competitor")
        for x in b.benchmarks:
            roles.setdefault(x, "benchmark")
    for b in project.brands:
        roles[b.name] = "self"
    return roles


def _has_role(project: Project, role: str):
    return (x for b in project.brands for x in (b.competitors if role == "competitor" else b.benchmarks))


def _uses_synthetic(materials: list[CaseMaterial], metrics: MetricsResult) -> bool:
    for m in materials:
        for fid in m.metric_fact_ids:
            f = metrics.registry.facts.get(fid)
            if f is not None and f.source == "synthetic_fixture":
                return True
        if m.source.source_type == "synthetic":
            return True
    return False


def _refresh_facts(p: Paragraph, pf: PartFactory) -> Paragraph:
    """Stored lead text keeps fact references; numbers are re-formatted from current values."""
    parts = []
    for part in p.parts:
        if part.type == "fact" and part.fact_id and part.fact_id in pf.registry:
            parts.append(pf.fact(part.fact_id, part.formatter or "int", bold=part.bold))
        else:
            parts.append(part.model_copy())
    return p.model_copy(update={"parts": parts})


def _case_lead(chunk: list[CaseMaterial]) -> list[Paragraph]:
    names = []
    for m in chunk:
        if m.entity and m.entity not in names:
            names.append(m.entity)
    who = "·".join(names) if names else "주요"
    return [P(T(f"{who} 캠페인 사례 — 활동 사실과 관측 성과"))]


def _used_sources(by_template: dict[str, list[SlideSpec]], materials: list[CaseMaterial]) -> list[tuple[SourceRef, str]]:
    used_ids = {sid for slides in by_template.values() for s in slides for sid in s.source_ids}
    out = []
    for m in materials:
        if m.source.id in used_ids and m.source.id not in {s.id for s, _ in out}:
            out.append((m.source, m.section_id))
    return out


def _assemble(project: Project, pages: list[SlideSpec], enabled: set[str], generated_on: date,
              synthetic: bool) -> list[SlideSpec]:
    pages_by_section = {ch: [s for s in pages if s.chapter == ch] for ch in CHAPTER_ORDER}
    sections_present = [ch for ch in CHAPTER_ORDER if pages_by_section[ch]]
    shown = _shown_numbers(sections_present)
    content: list[SlideSpec] = []
    for section in sections_present:
        if "divider" in enabled and section not in ("appendix", "exec"):
            content.append(_divider(section, shown[section], pages_by_section[section]))
        content += pages_by_section[section]
    out: list[SlideSpec] = []
    if "cover" in enabled:
        out.append(_cover(project, generated_on, synthetic))
    has_index = "index" in enabled and bool(sections_present)
    out += content
    if "end" in enabled:
        out.append(_end())
    if has_index:  # the index lists page numbers, so it is built once the order is known
        out.insert(1 if "cover" in enabled else 0, None)
    for no, slide in enumerate(out, start=1):
        if slide is not None:
            slide.page_no = no
    if has_index:
        i = out.index(None)
        out[i] = _index(project, sections_present, shown, pages_by_section, page_no=i + 1)
    for slide in out:
        if slide.page_role in ("content", "recap", "appendix", "index"):
            _korean_breadcrumb(slide, shown)
            slide.blocks = [*chrome_blocks(_chip(slide), slide.page_no), *slide.blocks]
    return out


def _korean_breadcrumb(slide: SlideSpec, shown: dict[str, str]) -> None:
    """v6 breadcrumb starts with the part number and name ('1. 인플루언서 · …'), not the English template title."""
    sec = slide.chapter if slide.chapter in shown else ("appendix" if slide.page_role == "appendix" else None)
    if not sec or sec not in shown:
        return
    for b in slide.blocks:
        if isinstance(b, TextBlock) and b.block_id == "title" and b.paragraphs and b.paragraphs[0].parts:
            first = b.paragraphs[0].parts[0]
            b.paragraphs[0].parts[0] = first.model_copy(update={"type": "meta", "key": "section_no",
                                                                "text": f"{shown[sec]}. {CHAPTERS[sec][1]}"})
            return


CHIPS = {"overview": "OVERVIEW", "owned": "OWNED", "search": "SEARCH", "influencer": "INFLUENCER", "recap": "RECAP",
        "appendix": "APPENDIX"}


def _chip(slide: SlideSpec) -> str:
    if slide.page_role == "index":
        return "INDEX"
    if slide.template_id.startswith("market"):
        return "MARKET"
    if slide.slide_id in ("ES", "SWOT", "NEXT"):
        return {"ES": "SUMMARY", "SWOT": "SWOT", "NEXT": "NEXT"}[slide.slide_id]
    if slide.section_id == "campaign":
        return "CASE"
    return CHIPS.get(slide.section_id or "", "FACTBOOK")


def _black(slide_id: str, template: str, role: str, title: str, blocks) -> SlideSpec:
    """Full-bleed navy frame (cover, part divider, end) — v6."""
    bg = ShapeBlock(block_id="bg", region=Region(x=0, y=0, w=1280, h=720), fill="navy")
    return SlideSpec(slide_id=slide_id, template_id=template, page_role=role, title=title, blocks=[bg, *blocks])


def _cover(project: Project, generated_on: date, synthetic: bool) -> SlideSpec:
    brands = "  ·  ".join(b.name for b in project.brands)
    rivals = "  ·  ".join(c for b in project.brands for c in b.competitors)
    blocks = [
        text_block("cover_kicker", "cover_kicker", Region(x=80, y=200, w=1120, h=24), [P(N(brands.upper()))],
                   spec="cover_kicker", color="gold"),
        text_block("cover_title", "cover_title", Region(x=80, y=229, w=1120, h=80), [P(N(project.name))],
                   spec="cover_title", valign="m", color="white"),
        text_block("cover_sub", "cover_sub", Region(x=80, y=315, w=1120, h=32),
                   [P(N(project.client), T("  ·  마케팅 진단 Factbook"))], spec="cover_sub", color="white"),
        ShapeBlock(block_id="cover_rule", region=Region(x=80, y=373, w=267, h=0), shape="line", line="gold",
                   line_width=1.5),
        text_block("cover_meta", "cover_meta", Region(x=80, y=560, w=1120, h=53),
                   [P(T("조사 범위  "), PERIOD(project.period.start, project.period.end), T("  ·  비교 브랜드  "), N(rivals)),
                    P(T("작성  "), D(f"{generated_on.year}.{generated_on.month:02d}"))],
                   spec="cover_meta", color="slate"),
    ]
    if synthetic:
        blocks.append(text_block("cover_badge", "badge", Region(x=80, y=620, w=400, h=24),
                                 [P(T("합성 테스트 자료로 생성한 데모", color="amber"))], spec="caption",
                                 color="amber", size=11, line=16))
    return _black("cover", "cover.v1", "cover", "표지", blocks)


def _shown_numbers(sections: list[str]) -> dict[str, str]:
    """Numbers as printed: consecutive over the sections actually in the deck (no gap when one is left out)."""
    out, n = {}, 0
    for s in sections:
        if CHAPTERS[s][0].isdigit():
            n += 1
            out[s] = str(n)
        else:
            out[s] = CHAPTERS[s][0]
    return out


PANEL_BRANDS = 3  # side-by-side panels one search slide holds


def _brand_groups(ctx: quant.QuantContext) -> list[tuple[int, quant.QuantContext]]:
    """(page number, context limited to that page's brands) — one page when there are 3 brands or fewer."""
    brands = ctx.project.brands
    if len(brands) <= PANEL_BRANDS:
        return [(1, ctx)]
    return [(k // PANEL_BRANDS + 1, replace(ctx, project=ctx.project.model_copy(update={"brands": brands[k:k + PANEL_BRANDS]})))
            for k in range(0, len(brands), PANEL_BRANDS)]


def _page_n(s: SlideSpec, n: int) -> SlideSpec:
    return s if n == 1 else s.model_copy(update={"slide_id": f"{s.slide_id}-{n}"})


def _index_row_cap(sections: list[str], rows: dict[str, list], top: float, bottom: float, columns: int = 3) -> int:
    """Largest rows-per-section that lets every section fit in `columns` columns of the index page."""
    longest = max((len(r) for r in rows.values()), default=0)
    for cap in range(max(longest, 1), 1, -1):
        col, y, fits = 1, float(top), True
        for s in sections:
            need = 35 + 3 + 25 * min(len(rows[s]), cap) + 12
            if y + need > bottom and y > top:
                col, y = col + 1, float(top)
            y += need
            fits = fits and y <= bottom + 12  # the trailing 12px gap may run past the bottom line
        if col <= columns and fits:
            return cap
    return 2


def _index(project: Project, sections: list[str], shown: dict[str, str], pages: dict[str, list[SlideSpec]],
           page_no: int) -> SlideSpec:
    """v6 index page: a navy bar per section, one tinted row per page with its page number."""
    blocks: list = [
        title_block("INDEX", sub_parts=[N(project.name)]),
        lead_block([P(N(project.name), T(" — "), M(str(len(sections)), "section_count"), T("개 장 구성"))]),
    ]
    col_w, gap, top, bottom = 370, 37, region("body").y, 650
    all_rows = {s: [(sl.title, sl.page_no) for sl in pages[s] if sl.parent_slide_id is None] for s in sections}
    cap = _index_row_cap(sections, all_rows, top, bottom)
    x, y = 48.0, float(top)
    for s in sections:
        label = CHAPTERS[s][1]
        rows = all_rows[s]
        if len(rows) > cap:  # long parts (many case pages) keep their first rows and summarize the rest
            rest = rows[cap - 1:]
            rows = rows[:cap - 1] + [(f"외 {len(rest)}장 (~{rest[-1][1]}쪽)", rest[0][1])]
        need = 35 + 3 + 25 * len(rows) + 12
        if y + need > bottom and y > top:
            x, y = x + col_w + gap, float(top)
        blocks += [ShapeBlock(block_id=f"idx_{s}_bar", region=Region(x=x, y=y, w=col_w, h=35), fill="navy"),
                   text_block(f"idx_{s}_head", "index_group", Region(x=x + 12, y=y, w=col_w - 24, h=35),
                              [P(M(f"{shown[s]}.", "section_no"), T(f" {label}"))], spec="index_group", valign="m",
                              color="white")]
        y += 38
        for k, (title, no) in enumerate(rows, start=1):
            code = f"{shown[s]}-{k}" if shown[s].isdigit() else f"{shown[s]}{k}"
            blocks += [ShapeBlock(block_id=f"idx_{s}_{k}_bg", region=Region(x=x, y=y, w=col_w, h=22), fill="tint"),
                       text_block(f"idx_{s}_{k}_code", "index_item", Region(x=x + 12, y=y, w=40, h=22),
                                  [P(M(code, "section_no"))], spec="index_item", valign="m", color="muted", weight="regular"),
                       text_block(f"idx_{s}_{k}_title", "index_item", Region(x=x + 58, y=y, w=col_w - 110, h=22),
                                  [P(N(cases._fit_one_line(title, col_w - 116, 10)))], spec="index_item", valign="m"),
                       text_block(f"idx_{s}_{k}_page", "index_item", Region(x=x + col_w - 48, y=y, w=36, h=22),
                                  [P(M(str(no), "page"))], spec="index_item", align="r", valign="m", color="muted",
                                  weight="regular")]
            y += 25
        y += 12
    return SlideSpec(slide_id="index", template_id="index.v2", page_role="index", title="INDEX", blocks=blocks,
                     page_no=page_no)


def _divider(section: str, shown_num: str, pages: list[SlideSpec]) -> SlideSpec:
    """v6 PART page: big part number, gold label, description, and the pages in this part on the right."""
    num, label, _, sub = CHAPTERS[section]  # slide id keeps the canonical number; the title shows shown_num
    blocks = [
        text_block("divider_title", "divider_title", Region(x=80, y=80, w=533, h=93),
                   [P(T("PART "), M(shown_num, "section_no"))], spec="divider_title", valign="m", color="white"),
        text_block("divider_sub", "divider_sub", Region(x=80, y=173, w=533, h=40), [P(T(label))], spec="divider_sub",
                   color="gold"),
        text_block("divider_desc", "divider_desc", Region(x=80, y=219, w=518, h=58), [P(T(sub))], spec="divider_desc",
                   color="mist"),
    ]
    items = [sl for sl in pages if sl.parent_slide_id is None][:26]
    # One column up to 12 pages; more pages flow into two columns instead of being cut off.
    cols = 1 if len(items) <= 12 else 2
    rows = math.ceil(len(items) / cols) if items else 1
    step = 40 if rows <= 12 else max(24, 520 // rows)
    col_x, title_w = ((700,), 430) if cols == 1 else ((640, 950), 240)
    for k, sl in enumerate(items, start=1):
        c, r = divmod(k - 1, rows)
        x, y = col_x[c], 110 + r * step
        blocks += [text_block(f"divider_code{k}", "divider_desc", Region(x=x, y=y, w=56, h=24),
                              [P(M(f"{shown_num}-{k}", "section_no"))], spec="divider_desc", valign="m", color="gold",
                              weight="semibold"),
                   text_block(f"divider_item{k}", "divider_desc", Region(x=x + 62, y=y, w=title_w, h=24),
                              [P(N(cases._fit_one_line(sl.title, title_w - 6, 10.5)))],
                              spec="divider_desc", valign="m", color="white")]
    return _black(f"section-{int(num):02d}", "divider.v2", "divider", label, blocks)


def _end() -> SlideSpec:
    return _black("end", "end.v1", "end", "E.O.D", [
        text_block("end_title", "end", Region(x=440, y=332, w=400, h=56), [P(T("E.O.D"))], spec="divider_sub",
                   align="c", valign="m", color="white", weight="heavy", size=28, line=36)])


def _bindings(slide: SlideSpec, metrics: MetricsResult, pf: PartFactory) -> list[Binding]:
    out: list[Binding] = []
    reg = metrics.registry

    def add(block_id: str, fact_id: str, formatter: str, display: str):
        obj = reg.get(fact_id)
        out.append(Binding(block_id=block_id, fact_id=fact_id, entity=getattr(obj, "entity", None),
                           metric=getattr(obj, "metric", "?"), unit=getattr(obj, "unit", "?"), formatter=formatter,
                           display=display))

    for b in slide.blocks:
        if isinstance(b, TextBlock):
            for p in b.paragraphs:
                for part in p.parts:
                    if part.type == "fact" and part.fact_id:
                        add(b.block_id, part.fact_id, part.formatter or "", part.display or "")
        elif isinstance(b, TableBlock):
            for r_i, row in enumerate(b.rows):
                for c_i, cell in enumerate(row.cells):
                    for p in cell.paragraphs:
                        for part in p.parts:
                            if part.type == "fact" and part.fact_id:
                                add(f"{b.block_id}[{r_i},{c_i}]", part.fact_id, part.formatter or "", part.display or "")
        elif isinstance(b, BarChartBlock):
            for it in b.items:
                add(b.block_id, it.fact_id, "share", it.display)
        elif isinstance(b, LineChartBlock):
            for s in b.series:
                for pt in s.points:
                    if pt.fact_id:
                        add(b.block_id, pt.fact_id, "index", pf.fact(pt.fact_id, "index").display or "")
    return out


def _notes(slide: SlideSpec, metrics: MetricsResult) -> str:
    lines = []
    for b in slide.blocks:
        if isinstance(b, TextBlock) and b.role in ("lead", "takeaway", "caption"):
            text = " / ".join(p.plain() for p in b.paragraphs if p.parts)
            if text:
                lines.append(f"[{b.role}] {text}")
    if slide.finding_ids:
        lines.append("Finding: " + ", ".join(slide.finding_ids))
    fact_ids = sorted({bd.fact_id for bd in slide.bindings})
    if fact_ids:
        raw = sorted({r for f in fact_ids for r in metrics.registry.lineage(f)})
        lines.append(f"근거 Fact {len(fact_ids)}개 (원본 {len(raw)}개): " + ", ".join(fact_ids[:30]) + (" …" if len(fact_ids) > 30 else ""))
    if slide.source_ids:
        lines.append("Source: " + ", ".join(slide.source_ids))
    return "\n".join(lines)


def fingerprint(inputs: BuildInputs) -> str:
    """Hash of everything a deck depends on; a different value means the deck is stale."""
    payload = {
        "project": inputs.project.model_dump(mode="json"),
        "facts": sorted((f.id, f.verification_status, f.conflict_key or "") for f in inputs.facts),
        "posts": sorted((p.batch_id or "", p.post_id, p.verification_status) for p in inputs.posts),
        "materials": sorted(json.dumps(m.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) for m in inputs.materials),
        "omitted": inputs.omitted_slots,
        "leads": {k: [p.model_dump(mode="json") for p in v] for k, v in sorted(inputs.lead_overrides.items())},
        **({"synthesis": inputs.synthesis} if inputs.synthesis else {}),  # absent = same hash as before it existed
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
