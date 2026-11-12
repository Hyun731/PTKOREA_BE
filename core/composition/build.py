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
from typing import Callable, Optional, Union

from core.composition import axes, cases, commerce, compare, customer, demand, overview, owned, quant, synthesis
from core.composition.chrome import (
    D, M, N, P, PERIOD, PartFactory, T, chrome_blocks, headline_blocks, insight_blocks, lead_block, synthetic_badge,
    text_block, title_block,
)
from core.composition.tokens import region
from core.metrics.derived import DerivedInputs, derive, measured_on
from core.metrics.engine import MetricsResult, compute
from core.rules.config import RulesConfig
from core.rules.engine import run_rules
from core.schemas.facts import Fact, Finding, Post
from core.schemas.materials import AssetRef, CaseMaterial, OwnedPostRef, ReviewSnapshotRef, SourceRef
from core.schemas.project import Brand, Project
from core.schemas.slidespec import (
    BarChartBlock, Binding, DeckSpec, Headline, LineChartBlock, Paragraph, Region, ShapeBlock, SlideSpec, SlotPlan,
    TableBlock, TextBlock,
)

# section_id: (number, label, index group, divider subtitle)
SECTIONS: dict[str, tuple[str, str, str, str]] = {
    "overview": ("1", "마케팅 Overview", "Overview", "브랜드 · 카테고리 · 타겟 매핑"),
    "owned": ("2", "자사 채널 점검", "Owned", "채널 인벤토리 · 팔로워 · 게시 빈도"),
    "search": ("2", "검색 경쟁", "Check", "브랜드명 · 카테고리 조합어 · 키 타겟 검색 점유"),
    "influencer": ("3", "인플루언서", "Check", "크리에이터 게시물 관측 지표"),
    "campaign": ("4", "캠페인·시장 사례", "Check", "활동 사실 · 관측 성과 · 근거"),
    "voc": ("5", "소비자 원문", "Customer", "카페·블로그·커뮤니티 원문 · 인식 경로"),
    "recap": ("5", "Recap", "Insight", "본문 근거 요약"),
    "appendix": ("A", "Appendix", "Appendix", "출처"),
}
TEMPLATE_SECTION = {"1-1": "overview", "1-6": "overview", "2-1": "owned", "2-2": "owned", "2-4": "owned",
                    "2-5": "owned", "2-8a": "search", "2-8b": "search", "2-8c": "search", "2-8d": "search",
                    "3-1": "influencer", "C1": "campaign", "C2": "campaign", "M1": "campaign", "M2": "campaign",
                    "TR1": "search_trend", "CM1": "commerce_review", "CM2": "commerce_review",
                    "5-1": "voc", "5-2": "voc", "5-recap": "recap", "A-source": "appendix",
                    "ES": "recap", "INSIGHT": "recap", "SWOT": "recap", "PROBLEM": "recap", "SOLUTION": "recap"}
TEMPLATE_SECTION.update({
    "OW-CMP": "owned",
    "MN1": "search",
    "BL1": "voc",
    "VC1": "voc",
    "PP1": "voc",
    "SH1": "search_trend",
    # P4-4 리서치 5대 축
    "MK1": "campaign", "DM1": "search_trend", "PL1": "campaign", "CS1": "voc", "5-3": "voc", "5-4": "voc",
})  # P3 비교·차트 장
TEMPLATE_LABEL = {"1-1": "브랜드·카테고리·타겟 매핑", "1-6": "타겟·채널별 캠페인 매트릭스", "2-1": "채널 인벤토리",
                  "2-2": "운영 공백 분석", "2-4": "브랜드별 상위 게시물", "2-5": "YouTube 채널 성과",
                  "2-8a": "브랜드명 검색 점유", "2-8b": "월별 검색 지수", "2-8c": "조합어 검색 점유",
                  "2-8d": "키 타겟 검색 점유", "3-1": "크리에이터 게시물", "C1": "캠페인 사례 카드", "C2": "사례 상세",
                  "M1": "시장·타겟 근거", "M2": "업종 KPI", "TR1": "검색 추이(Google Trends)",
                  "CM1": "판매·리뷰 자산", "CM2": "경쟁사 리뷰 비교",
                  "5-1": "소비자 인식 원문", "5-2": "브랜드 인식 경로",
                  "5-recap": "Recap", "A-source": "출처 표", "ES": "Executive Summary", "INSIGHT": "핵심 인사이트",
                  "SWOT": "SWOT", "PROBLEM": "문제 정의", "SOLUTION": "솔루션 방향"}
TEMPLATE_LABEL.update({
    "OW-CMP": "자사 vs 경쟁사 채널 비교",
    "MN1": "채널별 언급량 비교",
    "BL1": "블로그 문서 유형",
    "VC1": "커뮤니티별 부정 비율",
    "PP1": "페인 포인트",
    "SH1": "품목별 쇼핑 수요·성수기",
    "MK1": "시장 규모·성장", "DM1": "품목별 수요·시즌", "PL1": "정책·규제", "CS1": "소비자 인사이트",
    "5-3": "구매 여정", "5-4": "구매 상황 지도",
})
SECTION_ORDER = ["overview", "owned", "search", "influencer", "campaign", "voc", "recap", "appendix"]
# The deck reads as the 3C table of contents (팩트북 표준 목차): chapter → (number, label, index group, divider text).
# A slide keeps its content section (what it shows, used by checks) and also gets the chapter it sits in.
CHAPTERS: dict[str, tuple[str, str, str, str]] = {
    "exec": ("ES", "Executive Summary", "Summary", "핵심 요약"),
    "overview": ("1", "브랜드 비교", "Overview", "브랜드 매핑 · 자사 채널 · 검색 점유 비교"),  # several self brands only
    "company": ("1", "자사 분석", "Company", "자사 채널 · 인플루언서 · 캠페인"),
    "competitor": ("2", "경쟁사 분석", "Competitor", "시장 · 검색 경쟁 · 경쟁사와 벤치마크 사례"),
    "customer": ("3", "소비자 분석", "Customer", "인식 · 구매 여정"),
    "summary": ("4", "종합", "Insight", "인사이트 · SWOT · 문제·솔루션"),
    "appendix": ("A", "Appendix", "Appendix", "출처"),
}
CHAPTER_ORDER = list(CHAPTERS)
# With several self brands each one gets its own 자사·경쟁사·소비자·요약 parts ("company:B1"), so one
# brand's cases never get lost among another's. Pages that set each brand's own competition set in
# separate panels (v6 p26~p28, channel tables) stay shared: they open the deck as 브랜드 비교. "exec"
# (Executive Summary) is also per self brand — Phase 3-1: 자사 브랜드가 여럿이면 브랜드마다 따로 쓴다.
# 2-8d(키 타겟 점유)와 Recap은 발견 사항을 문장으로 나열하므로 브랜드마다 따로 만든다(P2-1): 한 장에
# 모으면 자사 브랜드들의 발견이 한 문단에 나란히 놓여 자사 브랜드끼리 비교가 된다(QC SELF_BRAND_COMPARISON).
BRAND_CHAPTERS = ("company", "competitor", "customer", "summary", "exec")
SIDE_BY_SIDE = {"1-1", "2-1", "2-2", "2-4", "2-5", "2-8a", "2-8b", "2-8c", "M1"}
TEMPLATE_CHAPTER = {"1-1": "company", "1-6": "company", "2-1": "company", "2-2": "company", "2-4": "company",
                    "2-5": "company", "3-1": "company", "C1": "company", "C2": "company", "M1": "competitor",
                    "M2": "competitor", "TR1": "competitor", "CM1": "company", "CM2": "competitor",
                    "2-8a": "competitor", "2-8b": "competitor",
                    "2-8c": "competitor", "2-8d": "competitor", "5-1": "customer", "5-2": "customer",
                    "5-recap": "summary", "A-source": "appendix", "ES": "exec", "INSIGHT": "summary",
                    "SWOT": "summary", "PROBLEM": "summary", "SOLUTION": "summary"}
TEMPLATE_CHAPTER.update({"OW-CMP": "company", "MN1": "competitor", "BL1": "customer", "VC1": "customer",
                         "PP1": "customer", "SH1": "competitor",
                         "MK1": "competitor", "DM1": "competitor", "PL1": "competitor", "CS1": "customer",
                         "5-3": "customer", "5-4": "customer"})
# P3 비교·차트 장은 같은 자료를 쓰는 기존 장이 켜져 있으면 함께 켜진다(따로 켜도 된다).
FOLLOWS = {"OW-CMP": "2-1",
           # P4-4 5대 축: 시장 자료(M1)가 켜지면 시장 규모·정책 장, 검색 추이(TR1)가 켜지면 수요 장,
           # 소비자 원문(5-1)이 켜지면 소비자 인사이트 장도 함께 — 자료가 모자라면 만들지 않는다.
           "MK1": "M1", "PL1": "M1", "DM1": "TR1", "CS1": "5-1"}
# Order of pages inside the deck; case pages come per group (자사 → 경쟁사 → 벤치마크).
PAGE_ORDER = ["ES", "1-1", "2-1", "OW-CMP", "2-2", "2-4", "2-5", "3-1", "C1", "C2", "1-6", "CM1", "MK1", "DM1", "PL1", "M1", "M2",
              "2-8a", "2-8b", "2-8c", "2-8d", "MN1", "SH1", "TR1", "CM2", "C1c", "C2c", "C1b", "C2b", "CS1", "5-3", "5-4",
              "BL1", "VC1", "PP1", "5-1", "5-2", "5-recap", "INSIGHT", "SWOT",
              "PROBLEM", "SOLUTION", "A-source"]
# (key, role, chapter, card prefix, detail prefix, title_main, title_sub)
CASE_GROUPS = [("self", "company", "C1", "C2", "Campaign", "캠페인 사례"),
               ("competitor", "competitor", "C1c", "C2c", "Competitor", "경쟁사 사례"),
               ("benchmark", "competitor", "C1b", "C2b", "Benchmark", "벤치마크 사례")]
TEMPLATE_ORDER = ["1-1", "1-6", "2-1", "2-2", "2-4", "2-5", "2-8a", "2-8b", "2-8c", "2-8d", "MN1", "SH1", "3-1", "C1", "C2", "M1",
                  "BL1", "VC1", "PP1", "5-1", "5-2", "5-recap", "A-source"]
FRAME_TEMPLATES = {"cover", "index", "divider", "end"}


@dataclass
class BuildInputs:
    project: Project
    facts: list[Fact]
    posts: list[Post] = field(default_factory=list)
    materials: list[CaseMaterial] = field(default_factory=list)
    owned_posts: list[OwnedPostRef] = field(default_factory=list)
    omitted_slots: dict[str, str] = field(default_factory=dict)  # slot_id -> reason
    # A person's headline per slide: Headline (claim + evidence) or, saved before P3-4, a claim-only list.
    lead_overrides: dict[str, Union[list[Paragraph], Headline]] = field(default_factory=dict)
    # A person's numbered insights per slide. An empty list intentionally hides the generated cards.
    insight_overrides: dict[str, list[dict]] = field(default_factory=dict)
    # AI writing made at deck build time (P3-4~), {kind: {slide_id: {"fp": body fingerprint, ...}}}; applied
    # only while the slide body still has the fingerprint it was written for.
    ai_writing: dict = field(default_factory=dict)
    # {brand_id: {"insight": {...}, "swot": {...}, "problem": {...}}} — active SynthesisRun per self brand.
    synthesis: dict = field(default_factory=dict)
    # P5-1 브랜드 진단 {brand_id: Diagnosis dict} — 자사 브랜드마다 활성 버전(core.schemas.diagnosis).
    diagnosis: dict = field(default_factory=dict)
    # {brand_id: [query, ...]} — Phase 3-4 Google Trends 연관 검색어, 그 브랜드의 최신 search_trend 수집 결과.
    trend_related: dict[str, list[str]] = field(default_factory=dict)
    # Phase 2 커머스 리뷰(CM1/CM2) — 채택 여부와 무관하게 전부 싣고, composition이 accepted만 골라 쓴다.
    reviews: list[ReviewSnapshotRef] = field(default_factory=list)
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
    # P1-2: 원문·댓글·리뷰에서 만든 파생 수치도 다른 Fact와 같은 레지스트리에 넣어 차트·헤드라인이 쓰게 한다.
    derived_facts = derive(DerivedInputs(project=project, materials=inputs.materials, owned_posts=inputs.owned_posts,
                                         reviews=inputs.reviews,
                                         measured_at=measured_on(project, inputs.materials, inputs.reviews),
                                         min_n=cfg.derived_min_n))
    metrics = compute(project, [*inputs.facts, *derived_facts], inputs.posts, cfg)
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
    enabled |= {t for t, parent in FOLLOWS.items() if parent in enabled}
    plan: list[SlotPlan] = []
    by_template: dict[str, list[SlideSpec]] = {}

    built: list[tuple[int, int, SlideSpec]] = []  # (page order rank, call order, slide)
    multi = len(project.brands) > 1

    def _slide_fact_ids(slides: list[SlideSpec]) -> set[str]:
        found: set[str] = set()

        def walk(value) -> None:
            if isinstance(value, dict):
                if value.get("fact_id"):
                    found.add(value["fact_id"])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for slide in slides:
            walk(slide.model_dump())
        return found

    def _thin_reason(template: str, slides: list[SlideSpec], density: Optional[dict[str, int]]) -> Optional[str]:
        rule = cfg.density_rules.get(template, {})
        measure = rule.get("measure")
        minimum = int(rule.get("min", 0))
        actual: Optional[int] = None
        if measure == "channels":
            actual = len({metrics.registry.facts[fid].dims.get("channel") for fid in _slide_fact_ids(slides)
                          if fid in metrics.registry.facts and metrics.registry.facts[fid].dims.get("channel")})
        elif measure and density:
            actual = density.get(measure)
        if minimum and actual is not None and actual < minimum:
            return f"자료가 적어 {rule.get('merge_into', '관련 분석')} 장에 합쳤습니다"

        for slide in slides:
            for block in slide.blocks:
                if isinstance(block, LineChartBlock) and any(
                        sum(point.value is not None for point in series.points) < cfg.line_chart_min_points
                        for series in block.series):
                    return f"자료가 적어 {rule.get('merge_into', '관련 분석')} 장에 합쳤습니다"
        return None

    def slot(slot_id: str, template: str, slides: list[SlideSpec], missing_reason: str, brand_id: Optional[str] = None,
             label: Optional[str] = None, chapter: Optional[str] = None, key: Optional[str] = None,
             part: Optional[str] = None, density: Optional[dict[str, int]] = None):
        """`part`: the self brand whose section this slot sits in (several self brands only)."""
        base = slot_id
        if part:
            tag = f"-{part}"
            slot_id = slot_id if tag in slot_id else slot_id + tag
            brand_id = brand_id or part
            name = project.brand(part).name
            label = label or TEMPLATE_LABEL[template]
            label = label if name in label else f"{label} · {name}"
            for sl in slides:
                if tag not in sl.slide_id:
                    sl.slide_id += tag
                if sl.parent_slide_id and tag not in sl.parent_slide_id:
                    sl.parent_slide_id += tag
                sl.brand_id = sl.brand_id or part
        if slot_id in inputs.omitted_slots or (part and base in inputs.omitted_slots):
            reason = inputs.omitted_slots.get(slot_id) or inputs.omitted_slots[base]
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="omitted",
                                 reason=reason))
            return
        thin = _thin_reason(template, slides, density) if slides else None
        if thin:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="thin",
                                 reason=thin))
        elif slides:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="ready",
                                 slide_ids=[s.slide_id for s in slides]))
            by_template.setdefault(template, []).extend(slides)
            if multi and not part and template in SIDE_BY_SIDE and template != "5-recap":
                chapter = "overview"
            for s in slides:
                s.chapter = chapter or TEMPLATE_CHAPTER[template]
                if part and s.chapter in BRAND_CHAPTERS:
                    s.chapter = f"{s.chapter}:{part}"
                built.append((PAGE_ORDER.index(key or template), len(built), s))
        else:
            plan.append(SlotPlan(slot_id=slot_id, section_id=TEMPLATE_SECTION[template], template_id=template,
                                 brand_id=brand_id, label=label or TEMPLATE_LABEL[template], readiness="needs_input",
                                 reason=missing_reason))

    # Order matters: leads are assigned to the first page that can show a finding.
    if "1-1" in enabled:
        s = overview.brand_mapping_page(ctx)
        slot("1-1", "1-1", [s] if s else [], "브랜드 설정 없음")

    def brand_part(c: quant.QuantContext, mats: list[CaseMaterial], owned_posts: list[OwnedPostRef],
                   part: Optional[str], which: str = "all") -> None:
        """Pages about one self brand (`part`), or about all of them with `part` None. `which`: "all",
        "shared" (only the pages that set every self brand side by side) or "own" (all the others)."""
        def on(template: str) -> bool:
            return template in enabled and (which == "all" or (template in SIDE_BY_SIDE) == (which == "shared"))

        if on("1-6"):
            s = overview.campaign_matrix_page(c.project, mats)
            slot("1-6", "1-6", [s] if s else [], "타겟이 분류된 채택 캠페인 사례 없음", part=part)
        if on("2-1"):
            s = owned.channel_inventory_page(c)
            slot("2-1", "2-1", [s] if s else [], "공식 계정 전체 게시물 데이터 없음(Brand.official_profiles 확인)", part=part)
        if on("OW-CMP"):
            # 자사 하나 + 그 경쟁사만(원칙 8): 다른 자사 브랜드는 경쟁사 목록에 있어도 빼고 그린다.
            slot("OW-CMP", "OW-CMP", owned.channel_compare_page(c, frozenset(b.name for b in project.brands)),
                 "경쟁사 공식 계정 수치 없음(설정에서 경쟁사 공식 계정 확인 후 수집·확인 필요)", part=part)
        if on("2-2"):
            s = owned.operating_gap_page(c)
            slot("2-2", "2-2", [s] if s else [],
                 "공백 구간(자체 게시 0건 달) 없음 — 해당 사항 없으면 생략 처리, 2-1 데이터 미확보면 2-1부터 확인", part=part)
        if on("2-4"):
            s = owned.top_posts_page(c.project, owned_posts)
            slot("2-4", "2-4", [s] if s else [], "이미지가 채택된 상위 게시물 없음", part=part)
        if on("2-5"):
            s = owned.youtube_performance_page(c)
            slot("2-5", "2-5", [s] if s else [], "YouTube 채널 데이터 없음(Brand.official_profiles 확인)", part=part)
        # The search slides put brands side by side in at most 3 panels: more brands continue on the next page.
        groups = _brand_groups(c)
        if on("2-8a"):
            pages = [_page_n(s, n) for n, c in groups if (s := quant.search_share(c))]
            slot("2-8a", "2-8a", pages, "12M 브랜드명 검색 세트(자사+경쟁사 전원) 미확보", part=part)
        if on("2-8b"):
            pages = [_page_n(s, n) for n, c in groups if (s := quant.search_trend(c))]
            slot("2-8b", "2-8b", pages, "공통 스케일 월별 검색 지수 미확보", part=part)
        if on("2-8c"):
            pages = [(n, p) for n, c in groups for p in quant.combo_share_pages(c)]
            if pages:
                for n, p in pages:
                    cat = p.slide_id.removeprefix("2-8c-")
                    p = _page_n(p, n)
                    slot(p.slide_id, "2-8c", [p], "", label=f"조합어 검색 점유 · +{cat}" + (f" ({n})" if n > 1 else ""), part=part)
            else:
                slot("2-8c", "2-8c", [], "카테고리 조합어(cat) 검색 세트 미확보", part=part)
        if on("2-8d"):
            s = quant.target_table(c)
            slot("2-8d", "2-8d", [s] if s else [], "전체·타겟 9M 검색 세트 미확보", part=part)
        if on("MN1"):
            s = compare.mention_page(c, frozenset(b.name for b in project.brands))
            slot("MN1", "MN1", [s] if s else [], "자사·경쟁사 채널별 언급량이 2개 채널 이상 필요", part=part)
        if on("DM1"):  # P4-4: the same demand page, placed with the other market axes (SH1 is then not repeated)
            s = demand.shopping_demand_page(c)
            if s:
                s.slide_id, s.title = "DM1", TEMPLATE_LABEL["DM1"]
            slot("DM1", "DM1", [s] if s else [], "월별 쇼핑 클릭 지수가 4개 이상인 제품군 없음", part=part)
        elif on("SH1"):
            s = demand.shopping_demand_page(c)
            slot("SH1", "SH1", [s] if s else [], "월별 쇼핑 클릭 지수가 4개 이상인 제품군 없음", part=part)
        if on("3-1"):
            for b in c.project.brands:
                slot(f"3-1-{b.id}", "3-1", quant.creator_pages(c, b.id), "기간 내 채택된 creator 게시물 없음", b.id,
                     f"크리에이터 게시물 · {b.name}", part=part)
        campaign_ordered = _case_order(project, [m for m in mats if m.section_id == "campaign"])
        roles = _case_roles(project)
        for role, chapter, card_id, detail_id, title_main, title_sub in CASE_GROUPS:
            campaign = [m for m in campaign_ordered if roles.get(m.entity or "", "self") == role]
            if role != "self" and not campaign and not any(_has_role(c.project, role)):
                continue  # no benchmark set: no empty benchmark slot either
            what = {"self": "사례", "competitor": "경쟁사 사례", "benchmark": "벤치마크 사례"}[role]
            if on("C1"):
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
                slot(card_id, "C1", pages, reason, label=f"{title_sub} 카드", chapter=chapter, key=card_id, part=part)
            if on("C2"):
                detail_cases = campaign
                if "C1" in enabled and any(m.featured for m in campaign):
                    detail_cases = [m for m in campaign if m.featured]  # the rest are on the C1 grid
                detail = cases.case_detail_pages(detail_cases, pf, badge if _uses_synthetic(detail_cases, metrics) else [],
                                                 prefix=detail_id)
                slot(detail_id, "C2", detail, f"채택된 {what} 자료 없음 (이미지·근거 문장 채택 필요)", label=f"{title_sub} 상세",
                     chapter=chapter, key=detail_id, part=part)
        if not multi and (on("M1") or on("MK1") or on("PL1")):
            # Several self brands: handled once per distinct category, below (Phase 3-2).
            category = c.project.brands[0].categories[0] if c.project.brands[0].categories else c.project.brands[0].name
            market = [m for m in mats if m.section_id == "market" and m.entity == category]
            _market_family(c, category, market, enabled, slot, badge if _uses_synthetic(market, metrics) else [],
                           part=part)
        self_name = c.project.brands[0].name if c.project.brands else None
        self_id = c.project.brands[0].id if c.project.brands else None
        if on("M2"):
            # KPI materials carry a real brand/competitor name as entity, so the usual name filter
            # above already scopes `mats` correctly per brand — no category dedup needed (unlike M1).
            kpi = [m for m in mats if m.section_id == "market_kpi"]
            slot("M2", "M2", cases.kpi_pages(kpi, pf, self_name, badge if _uses_synthetic(kpi, metrics) else []),
                 "채택된 업종 KPI 근거 없음", part=part)
        reviews = [r for r in inputs.reviews if r.brand_id == self_id] if self_id else []
        if on("CM1"):
            slot("CM1", "CM1", commerce.review_asset_page(reviews, self_name),
                 "채택된 리뷰 스냅샷 없음(대표 상품 확정·수집 필요)", part=part)
        if on("TR1"):
            related = inputs.trend_related.get(self_id, []) if self_id else []
            slot("TR1", "TR1", [s] if (s := quant.trend_page(c, related)) else [],
                 "Google Trends 수집 결과 없음(요청 빈도 제한으로 자주 막힘)", part=part)
        if on("CM2"):
            slot("CM2", "CM2", commerce.competitor_review_page(reviews),
                 "채택된 경쟁사 리뷰 스냅샷 없음", part=part)
        voc = [m for m in mats if m.section_id == "voc" and m.entity == self_name]
        usable_voc = [m for m in voc if m.review_status == "accepted" and not m.voc_sponsored and m.voc_sentiment]
        awareness_voc = [m for m in usable_voc if m.voc_awareness]
        if on("5-1"):
            s = customer.voc_summary_page(c.project, voc)
            slot("5-1", "5-1", [s] if s else [], "채택된 소비자 원문 없음(긍정·부정 분류 필요)", part=part,
                 density={"sources": len(usable_voc)})
        if on("5-2"):
            s = customer.awareness_channel_page(c.project, voc)
            slot("5-2", "5-2", [s] if s else [], "인식 경로가 드러난 소비자 원문 없음", part=part,
                 density={"sources": len(awareness_voc)})
        if on("BL1"):
            s = compare.blog_type_page(c, frozenset(b.name for b in project.brands))
            slot("BL1", "BL1", [s] if s else [], "유형이 분류된 블로그 검색어 표본 20건 이상 없음", part=part)
        if on("VC1"):
            s = demand.voc_negative_page(c, voc)
            voc_n = max((int(f.dims.get("n", 0)) for f in metrics.registry.facts.values()
                         if f.brand_id == self_id and f.entity == self_name and f.metric == "voc_negative_rate"),
                        default=0)
            slot("VC1", "VC1", [s] if s else [], "출처별 부정 비율과 채택 원문이 부족함", part=part,
                 density={"sources": voc_n})
        if on("PP1"):
            s = demand.pain_point_page(c, voc)
            slot("PP1", "PP1", [s] if s else [], "원문 수가 있는 페인 포인트 3개 이상 없음", part=part)
        if on("CS1"):
            s = axes.consumer_insight_page(c, voc)
            slot("CS1", "CS1", [s] if s else [], "구매 결정 요인과 페인 포인트가 각각 3개 이상 필요(소비자 원문 채택·분류)",
                 part=part, density={"sources": max((int(f.dims.get("n", 0)) for f in metrics.registry.facts.values()
                                                      if f.brand_id == self_id and f.metric == "pain_point_count"),
                                                     default=0)})
        if on("5-recap"):
            s = quant.recap(c)
            slot("5-recap", "5-recap", [s] if s else [], "요약할 Finding 없음", part=part)
        # 종합 장표(Phase 3-1): 자사 브랜드마다 따로, 고른 유형만 — 쓴 적 없으면 빈 슬롯도 만들지 않는다.
        if which != "shared":
            brand_id = c.project.brands[0].id if c.project.brands else None
            synth = inputs.synthesis.get(brand_id, {}) if brand_id else {}
            for key, type_key, page_fn in (
                ("ES", "insight", synthesis.es_page), ("INSIGHT", "insight", synthesis.insight_page),
                ("SWOT", "swot", synthesis.swot_page), ("PROBLEM", "problem", synthesis.problem_page),
                ("SOLUTION", "problem", synthesis.solution_page),
            ):
                data = synth.get(type_key)
                if data and (s := page_fn(data, pf)):
                    slot(key, key, [s], "", part=part)
            # P4-4 생성형 장(P5-1과 공유): 구매 여정·구매 상황 지도 — 쓴 적 없으면 빈 슬롯도 만들지 않는다.
            for key, page_fn in (("5-3", axes.journey_page), ("5-4", axes.situation_page)):
                data = synth.get({"5-3": "journey", "5-4": "situation"}[key])
                if data and (s := page_fn(data)):
                    slot(key, key, [s], "", part=part)

    if not multi:
        brand_part(ctx, inputs.materials, inputs.owned_posts, None)
    else:
        brand_part(ctx, inputs.materials, inputs.owned_posts, None, "shared")
        for i, b in enumerate(project.brands):
            names = {b.name, *b.competitors, *b.benchmarks}
            # A case belongs to every brand that lists its entity (a shared competitor shows in each);
            # unnamed market notes go by brand, and those without one go with the first brand.
            mats = [m for m in inputs.materials if (m.entity in names if m.entity else
                                                    m.brand_id == b.id or (m.brand_id is None and i == 0))]
            c = replace(ctx, project=project.model_copy(update={"brands": [b]}),
                        findings=[f for f in findings if f.brand_id == b.id])
            brand_part(c, mats, [o for o in inputs.owned_posts if o.brand_id == b.id], b.id, "own")
        _market_by_category(ctx, inputs.materials, enabled, slot, badge, metrics)
    if "A-source" in enabled:
        srcs = _used_sources(by_template, inputs.materials)
        slot("A-source", "A-source", cases.source_pages(srcs, []), "사용한 출처 없음")

    ordered = _assemble(project, [s for _, _, s in sorted(built, key=lambda x: (x[0], x[1]))], enabled,
                        inputs.generated_on or date.today(), synthetic)
    _apply_headlines(ordered, inputs, pf)
    _apply_page_insights(ordered, inputs, pf)
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


def _market_by_category(ctx: quant.QuantContext, materials: list[CaseMaterial], enabled: set[str], slot: Callable,
                        badge: list, metrics: MetricsResult) -> None:
    """M1 산업 카테고리 분석(Phase 3-2)과 시장 축(P4-4 MK1·PL1): 자사 카테고리마다 한 번 — 두 브랜드가
    같은 카테고리면 브랜드 비교 장처럼 한 번만 공유하고, 다르면 각자의 장에 따로 둔다."""
    if not {"M1", "MK1", "PL1"} & enabled:
        return
    owners: dict[str, list[Brand]] = {}
    for b in ctx.project.brands:
        cat = b.categories[0] if b.categories else b.name
        owners.setdefault(cat, []).append(b)
    market = [m for m in materials if m.section_id == "market"]
    shared_n = 0
    for cat, owning in owners.items():
        cat_mats = [m for m in market if m.entity == cat]
        c = replace(ctx, project=ctx.project.model_copy(update={"brands": owning}))
        cat_badge = badge if _uses_synthetic(cat_mats, metrics) else []
        tag = cat if len(owners) > 1 else None
        if len(owning) == 1:
            _market_family(c, cat, cat_mats, enabled, slot, cat_badge, part=owning[0].id, tag=tag)
            continue
        _market_family(c, cat, cat_mats, enabled, slot, cat_badge, tag=tag, suffix=f"-{shared_n}" if shared_n else "")
        shared_n += 1


def _market_family(c: quant.QuantContext, category: str, cat_mats: list[CaseMaterial], enabled: set[str],
                   slot: Callable, badge: list, *, part: Optional[str] = None, tag: Optional[str] = None,
                   suffix: str = "") -> None:
    """One category's market pages: MK1 시장 규모·성장, PL1 정책·규제 and M1 시장·타겟 근거 (P4-4). Policy notes
    get their own table only when there are enough of them; otherwise they stay rows of M1."""
    policy = axes.policy_materials(cat_mats)
    split = "PL1" in enabled and len(policy) >= int(c.config.density_rules.get("PL1", {}).get("min", 1))
    m1_mats = [m for m in cat_mats if m not in policy] if split else cat_mats

    def named(pages: list[SlideSpec], base: str) -> list[SlideSpec]:
        if suffix:  # a second shared category: M1-1, MK1-1, …
            for s in pages:
                s.slide_id = s.slide_id.replace(base, base + suffix, 1)
                if s.parent_slide_id:
                    s.parent_slide_id = base + suffix
        return pages

    def label(template: str) -> Optional[str]:
        return f"{TEMPLATE_LABEL[template]} · {tag}" if tag else None

    if "MK1" in enabled:
        figs = axes.market_figures(c, category, cat_mats)
        s = axes.market_size_page(c, category, cat_mats, figs)
        slot("MK1" + suffix, "MK1", named([s] if s else [], "MK1"), "채택된 시장 규모·연평균 성장률 수치 없음",
             label=label("MK1"), key="MK1", part=part,
             density={"figures": len(figs.get("size") or []) + len(figs.get("cagr") or [])})
    if "PL1" in enabled:
        slot("PL1" + suffix, "PL1", named(axes.policy_pages(policy, c.pf, badge, category), "PL1"),
             "채택된 정책·규제 자료 없음", label=label("PL1"), key="PL1", part=part, density={"policies": len(policy)})
    if "M1" in enabled:
        evidence_n = sum(m.review_status == "accepted" and any(x.review_status == "accepted" for x in m.claims)
                         for m in m1_mats)
        slot("M1" + suffix, "M1", named(cases.market_pages(m1_mats, c.pf, badge), "M1"), "채택된 시장·타겟 근거 없음",
             label=label("M1"), key="M1", part=part, density={"evidence": evidence_n})


def _refresh_facts(p: Paragraph, pf: PartFactory) -> Paragraph:
    """Stored lead text keeps fact references; numbers are re-formatted from current values."""
    parts = []
    for part in p.parts:
        if part.type == "fact" and part.fact_id and part.fact_id in pf.registry:
            parts.append(pf.fact(part.fact_id, part.formatter or "int", bold=part.bold))
        else:
            parts.append(part.model_copy())
    return p.model_copy(update={"parts": parts})


HEAD_ROLES = {"lead", "lead_evidence", "insight", "title", "chip", "page_no"}


def body_fingerprint(slide: SlideSpec) -> str:
    """Hash of what a page's body shows — everything but its headline, insights and frame (P3-4). AI writing
    is kept for a page only while this stays the same, so a sentence never outlives the numbers it cites."""
    body = [b.model_dump(mode="json", exclude={"region"}) for b in slide.blocks
            if not b.block_id.startswith(("chrome_", "insight")) and getattr(b, "role", None) not in HEAD_ROLES]
    payload = {"id": slide.slide_id, "template": slide.template_id, "title": slide.title, "body": body}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def lead_of(slide: SlideSpec) -> Optional[TextBlock]:
    return next((b for b in slide.blocks if isinstance(b, TextBlock) and b.role == "lead"), None)


def set_headline(slide: SlideSpec, head: Headline, pf: Optional[PartFactory] = None) -> None:
    """Swap a page's headline for `head` in the same area (claim on top, evidence lines under it)."""
    lead = lead_of(slide)
    if lead is None or not head.claim:
        return
    area = lead.region
    old_ev = next((b for b in slide.blocks if isinstance(b, TextBlock) and b.role == "lead_evidence"), None)
    if old_ev is not None:  # already split once: the area is both blocks together
        area = Region(x=area.x, y=area.y, w=area.w, h=old_ev.region.y + old_ev.region.h - area.y)
    claim = [_refresh_facts(p, pf) if pf else p for p in head.claim]
    evidence = [_refresh_facts(p, pf) if pf else p for p in head.evidence]
    if evidence:
        new = headline_blocks(claim, evidence, area)
    else:  # claim only: keep the template's own type and area
        new = [lead.model_copy(update={"block_id": "lead_claim", "paragraphs": claim, "region": area})]
    i = slide.blocks.index(lead)
    rest = [b for b in slide.blocks if b is not lead and b is not old_ev]
    slide.blocks = rest[:i] + new + rest[i:]


def _apply_headlines(slides: list[SlideSpec], inputs: BuildInputs, pf: PartFactory) -> None:
    """A person's headline wins; otherwise the AI headline written for this exact body (P3-4)."""
    ai = (inputs.ai_writing or {}).get("lead", {})
    for s in slides:
        if s.page_role not in ("content", "recap", "appendix") or lead_of(s) is None:
            continue
        if s.slide_id in inputs.lead_overrides:
            set_headline(s, Headline.coerce(inputs.lead_overrides[s.slide_id]), pf)
            s.needs_review = False
            continue
        w = ai.get(s.slide_id)
        if w and w.get("fp") == body_fingerprint(s) and _facts_known(w, pf):
            set_headline(s, Headline.coerce({"claim": w["claim"], "evidence": w.get("evidence") or []}), pf)
            s.needs_review = False


def _refresh_parts(parts: list[Part], pf: PartFactory) -> list[Part]:
    return _refresh_facts(Paragraph(parts=parts), pf).parts


def _set_page_insights(slide: SlideSpec, items: list[dict], pf: PartFactory) -> None:
    """Replace legacy inline findings with the shared P3-5 insight cards."""
    slide.blocks = [b for b in slide.blocks if not b.block_id.startswith("insight")]
    cards = []
    for item in items[:3]:
        title = _refresh_parts(Paragraph.model_validate(item.get("title") or {"parts": []}).parts, pf)
        body = _refresh_parts(Paragraph.model_validate(item.get("body_segments") or {"parts": []}).parts, pf)
        if title and body:
            cards.append((title, body))
    if cards:
        slide.blocks.extend(insight_blocks(cards))


def _apply_page_insights(slides: list[SlideSpec], inputs: BuildInputs, pf: PartFactory) -> None:
    """A person's P3-5 cards win; otherwise use AI cards written for this exact page body."""
    ai = (inputs.ai_writing or {}).get("insights", {})
    for s in slides:
        if s.page_role != "content" or lead_of(s) is None:
            continue
        if s.slide_id in inputs.insight_overrides:
            _set_page_insights(s, inputs.insight_overrides[s.slide_id], pf)
            continue
        writing = ai.get(s.slide_id)
        if writing and writing.get("fp") == body_fingerprint(s) and _facts_known(writing, pf):
            _set_page_insights(s, writing.get("insights") or [], pf)


def _facts_known(writing: dict, pf: PartFactory) -> bool:
    for key in ("claim", "evidence"):
        for p in writing.get(key) or []:
            for part in p.get("parts", []):
                if part.get("type") == "fact" and part.get("fact_id") not in pf.registry:
                    return False
    for item in writing.get("insights") or []:
        for key in ("title", "body_segments"):
            for part in (item.get(key) or {}).get("parts", []):
                if part.get("type") == "fact" and part.get("fact_id") not in pf.registry:
                    return False
    return True


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
    order = [*CHAPTER_ORDER[:2], *(f"{ch}:{b.id}" for b in project.brands for ch in BRAND_CHAPTERS),
             *CHAPTER_ORDER[2:]]
    pages_by_section = {ch: [s for s in pages if s.chapter == ch] for ch in order}
    sections_present = [ch for ch in order if pages_by_section[ch]]
    shown = _shown_numbers(sections_present)
    labels = {ch: chapter_label(project, ch) for ch in sections_present}
    content: list[SlideSpec] = []
    for section in sections_present:
        if "divider" in enabled and section not in ("appendix", "exec"):
            content.append(_divider(section, shown[section], labels[section], pages_by_section[section]))
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
        out[i] = _index(project, sections_present, shown, labels, pages_by_section, page_no=i + 1)
    for slide in out:
        if slide.page_role in ("content", "recap", "appendix", "index"):
            _korean_breadcrumb(slide, shown, labels)
            slide.blocks = [*chrome_blocks(_chip(slide), slide.page_no), *slide.blocks]
    return out


def chapter_label(project: Project, chapter: str) -> str:
    """'자사 분석', or '자사 분석 · 쌤소나이트' for one self brand's part of a multi-brand deck."""
    base, _, brand_id = chapter.partition(":")
    return f"{CHAPTERS[base][1]} · {project.brand(brand_id).name}" if brand_id else CHAPTERS[base][1]


def content_chapter(slide: SlideSpec) -> Optional[str]:
    """The 3C part a page's content belongs to, without the brand ("company:B1" → company); a
    side-by-side page under 브랜드 비교 goes by what it shows (search share → competitor)."""
    base = (slide.chapter or "").partition(":")[0] or None
    if base != "overview":
        return base
    keys = [k for k in TEMPLATE_CHAPTER if slide.slide_id == k or slide.slide_id.startswith(k + "-")]
    return TEMPLATE_CHAPTER[max(keys, key=len)] if keys else "company"


def _korean_breadcrumb(slide: SlideSpec, shown: dict[str, str], labels: dict[str, str]) -> None:
    """v6 breadcrumb starts with the part number and name ('1. 인플루언서 · …'), not the English template title."""
    sec = slide.chapter if slide.chapter in shown else ("appendix" if slide.page_role == "appendix" else None)
    if not sec or sec not in shown:
        return
    for b in slide.blocks:
        if isinstance(b, TextBlock) and b.block_id == "title" and b.paragraphs and b.paragraphs[0].parts:
            first = b.paragraphs[0].parts[0]
            b.paragraphs[0].parts[0] = first.model_copy(update={"type": "meta", "key": "section_no",
                                                                "text": f"{shown[sec]}. {labels[sec]}"})
            return


CHIPS = {"overview": "OVERVIEW", "owned": "OWNED", "search": "SEARCH", "influencer": "INFLUENCER", "voc": "VOC",
        "recap": "RECAP", "appendix": "APPENDIX"}


SYNTHESIS_CHIP = {"ES": "SUMMARY", "SWOT": "SWOT", "INSIGHT": "INSIGHT", "PROBLEM": "PROBLEM", "SOLUTION": "SOLUTION"}


def _chip(slide: SlideSpec) -> str:
    if slide.page_role == "index":
        return "INDEX"
    if slide.template_id.startswith("market"):
        return "MARKET"
    # Per self brand these carry a -{brand_id} suffix (slot(part=...)), same as other brand-scoped slides.
    key = next((k for k in SYNTHESIS_CHIP if slide.slide_id == k or slide.slide_id.startswith(k + "-")), None)
    if key:
        return SYNTHESIS_CHIP[key]
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
        if CHAPTERS[s.partition(":")[0]][0].isdigit():
            n += 1
            out[s] = str(n)
        else:
            out[s] = CHAPTERS[s.partition(":")[0]][0]
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


def _index(project: Project, sections: list[str], shown: dict[str, str], labels: dict[str, str],
           pages: dict[str, list[SlideSpec]], page_no: int) -> SlideSpec:
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
        label = labels[s]
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


def _divider(section: str, shown_num: str, label: str, pages: list[SlideSpec]) -> SlideSpec:
    """v6 PART page: big part number, gold label, description, and the pages in this part on the right."""
    base, _, brand_id = section.partition(":")
    num, _, _, sub = CHAPTERS[base]  # slide id keeps the canonical number; the title shows shown_num
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
    return _black(f"section-{int(num):02d}" + (f"-{brand_id}" if brand_id else ""), "divider.v2", "divider", label, blocks)


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
            for it in b.bar_items():  # every series of a grouped/stacked chart, not just one
                add(b.block_id, it.fact_id, it.formatter, it.display)
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
        "leads": {k: ([p.model_dump(mode="json") for p in v] if isinstance(v, list) else v.model_dump(mode="json"))
                  for k, v in sorted(inputs.lead_overrides.items())},
        **({"synthesis": inputs.synthesis} if inputs.synthesis else {}),  # absent = same hash as before it existed
        **({"ai_writing": inputs.ai_writing} if inputs.ai_writing else {}),
        **({"diagnosis": inputs.diagnosis} if inputs.diagnosis else {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
