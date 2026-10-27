"""Diagnostic-profile catalog: sections, channel support, ResearchPlan generation (PRD 3, 4, R05).

The client MVP's 24 items / 53 slides are not hard-coded: items follow the brands and
sections the planner actually selected.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from core.schemas.project import Project

SECTIONS = [
    {"id": "search", "label": "검색 경쟁", "templates": ["2-8a", "2-8b", "2-8c", "2-8d"],
     "data": "사용자가 보유한 검색 지수 CSV (자동 수집 없음)", "default_window": "9M (+12M 비교 창)"},
    {"id": "influencer", "label": "인플루언서", "templates": ["3-1"],
     "data": "공개 게시물 관측값(ScrapeCreators) 또는 posts CSV", "default_window": "프로젝트 기간"},
    {"id": "campaign", "label": "캠페인 사례", "templates": ["C1", "C2"],
     "data": "기사·공식 자료·게시물 URL + 이미지 + 근거 문장", "default_window": "사용자 지정"},
    {"id": "market", "label": "시장·타겟", "templates": ["M1"],
     "data": "공식 보고서·통계의 확인된 사실", "default_window": "사용자 지정"},
    {"id": "recap", "label": "Recap", "templates": ["5-recap"], "data": "본문 Finding 요약", "default_window": "-"},
    {"id": "appendix", "label": "출처 표", "templates": ["A-source"], "data": "사용 자료 출처", "default_window": "-"},
]
FRAMES = ["cover", "index", "divider", "end"]
# Search-index slides (2-8a~d) and the search-driven Recap are opt-in: there is no search-index provider
# (Naver APIs cannot be issued), so they only work from a search CSV the planner already has.
DEFAULT_SLIDES = ["cover", "index", "divider", "3-1", "C1", "C2", "M1", "A-source", "end"]
# The synthetic sample ships its own search CSV, so it keeps the search slides on.
SAMPLE_SLIDES = ["cover", "index", "divider", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1", "5-recap", "A-source", "end"]

# Channel support must match what can actually be collected (MVP_SITE_REVIEW 6).
CHANNELS = {
    "search_csv": {"label": "검색 지수 CSV (보유 자료)", "support": "manual_only", "provider": None},
    "web": {"label": "웹 기사·공식 자료", "support": "auto", "provider": "perplexity"},
    "instagram": {"label": "Instagram 공개 게시물", "support": "auto", "provider": "scrapecreators"},
    "youtube": {"label": "YouTube 공개 영상", "support": "auto", "provider": "scrapecreators"},
    "tiktok": {"label": "TikTok", "support": "manual_only", "provider": None},
    "naver_blog": {"label": "네이버 블로그·카페", "support": "manual_only", "provider": None},
    "offline": {"label": "오프라인·팝업", "support": "manual_only", "provider": None},
    "sales": {"label": "판매·매출 데이터", "support": "unsupported", "provider": None},
}
SECTION_CHANNELS = {
    "search": ["search_csv"],
    "influencer": ["instagram", "youtube"],
    "campaign": ["web", "instagram", "youtube"],
    "market": ["web"],
}


def shift_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def comparison_window(project: Project) -> tuple[date, date]:
    """12M comparison window ending at the main period end (shown as real dates)."""
    end = project.period.end
    start = shift_months(date(end.year, end.month, 1), -11)
    return start, end


def section_window(project: Project, section_id: str) -> tuple[date, date]:
    w = project.window_for(section_id)
    if w:
        return w.start, w.end
    return project.period.start, project.period.end


def generate_items(project: Project) -> list[dict]:
    enabled = set(project.enabled_slides)
    active = [s for s in SECTIONS if set(s["templates"]) & enabled and s["id"] in SECTION_CHANNELS]
    items: list[dict] = []
    order = 0

    def add(**kw):
        nonlocal order
        order += 1
        items.append({"order": order, **kw})

    for brand in project.brands:
        for sec in active:
            sid = sec["id"]
            start, end = section_window(project, sid)
            if sid == "search":
                add(brand_id=brand.id, entity=brand.name, role="self", section_id=sid,
                    question=f"{brand.name}·경쟁사({', '.join(brand.competitors)}) 브랜드명·조합어 검색 상대 지수",
                    period_start=start, period_end=end, channels=SECTION_CHANNELS[sid], required=True)
            elif sid == "influencer":
                add(brand_id=brand.id, entity=brand.name, role="self", section_id=sid,
                    question=f"{brand.name} 관련 크리에이터 공개 게시물(조회·반응·게시일)",
                    period_start=start, period_end=end, channels=SECTION_CHANNELS[sid], required=True)
            elif sid == "campaign":
                add(brand_id=brand.id, entity=brand.name, role="self", section_id=sid,
                    question=f"{brand.name} 캠페인·활동 사례", period_start=start, period_end=end,
                    channels=SECTION_CHANNELS[sid], required=True)
                for comp in brand.competitors:
                    add(brand_id=brand.id, entity=comp, role="competitor", section_id=sid,
                        question=f"경쟁사 {comp} 캠페인·활동 사례", period_start=start, period_end=end,
                        channels=SECTION_CHANNELS[sid], required=False)
                for bench in brand.benchmarks:
                    add(brand_id=brand.id, entity=bench, role="benchmark", section_id=sid,
                        question=f"벤치마크 {bench} 참고 사례 (경쟁 분모 제외)", period_start=start, period_end=end,
                        channels=SECTION_CHANNELS[sid], required=False)
            elif sid == "market":
                add(brand_id=brand.id, entity=brand.categories[0] if brand.categories else brand.name, role="market",
                    section_id=sid, question=f"{'·'.join(brand.categories) or brand.name} 시장·타겟 공식 자료",
                    period_start=start, period_end=end, channels=SECTION_CHANNELS[sid], required=False)
    return items


def channel_status(provider: Optional[str], configured: bool) -> str:
    if provider is None:
        return "manual_only"
    return "ready" if configured else "key_missing"
