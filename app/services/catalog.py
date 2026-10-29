"""Diagnostic-profile catalog: sections, channel support, comparison window (PRD 3, 4).

Research items themselves come from the scope catalog (app.services.scope).
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from core.schemas.project import Project

SECTIONS = [
    {"id": "owned", "label": "자사 채널 점검", "templates": ["2-1", "2-2", "2-4", "2-5"],
     "data": "공식 Instagram·YouTube 계정 전체 게시물(ScrapeCreators, Brand.official_profiles 필요)",
     "default_window": "프로젝트 기간"},
    {"id": "search", "label": "검색 경쟁", "templates": ["2-8a", "2-8b", "2-8c", "2-8d"],
     "data": "네이버 데이터랩 검색어트렌드(브랜드명, 자동) 또는 보유한 검색 지수 CSV(조합어·키 타겟)", "default_window": "9M (+12M 비교 창)"},
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
# Search-index slides (2-8a~d) stay opt-in by default even though 2-8a/2-8b (brand-name search,
# seg=all) now auto-collect via Naver DataLab: 2-8c(조합어)/2-8d(키 타겟) still need a search CSV,
# so turning the whole section on by default would silently leave two of four slides needs_input.
# 1-1 (브랜드·카테고리·타겟 매핑) needs no collector — it reads straight from the project's own
# brand/category/target config — so it is on by default for every project, unlike the search slides.
# 1-6 (캠페인 매트릭스) reuses already-collected, already-accepted campaign materials (same
# prerequisite C1/C2 already have), degrading to needs_input like they do until some are
# AI-tagged with a target_segment — on by default for the same reason.
# 2-1 (채널 인벤토리) is opt-in like the search slides: it needs Brand.official_profiles set
# explicitly (which handle is the brand's own account), not something every project has.
DEFAULT_SLIDES = ["cover", "index", "divider", "1-1", "1-6", "3-1", "C1", "C2", "M1", "A-source", "end"]
# The synthetic sample ships its own search CSV, so it keeps the search slides on.
SAMPLE_SLIDES = ["cover", "index", "divider", "1-1", "1-6", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1", "5-recap",
                 "A-source", "end"]

# Channel support must match what can actually be collected (MVP_SITE_REVIEW 6).
CHANNELS = {
    # Full own-account history (2-1 채널 인벤토리), not the single-post/hashtag-discovery
    # channels below. Needs the brand's handle in Brand.official_profiles.
    "instagram_owned": {"label": "Instagram 공식 계정 전체 게시물", "support": "auto", "provider": "scrapecreators"},
    "youtube_owned": {"label": "YouTube 공식 채널 전체 영상", "support": "auto", "provider": "scrapecreators"},
    # Brand-name search share/trend (2-8a, 2-8b; seg=all). Combination keywords (2-8c) and
    # target-segment filters (2-8d) have no config surface yet, so they stay CSV-only.
    "search_naver": {"label": "네이버 데이터랩 검색어트렌드 (브랜드명)", "support": "auto", "provider": "naver"},
    "search_csv": {"label": "검색 지수 CSV (보유 자료 · 조합어·키 타겟)", "support": "manual_only", "provider": None},
    "web": {"label": "웹 기사·공식 자료", "support": "auto", "provider": "perplexity"},
    "instagram": {"label": "Instagram 공개 게시물", "support": "auto", "provider": "scrapecreators"},
    "youtube": {"label": "YouTube 공개 영상", "support": "auto", "provider": "scrapecreators"},
    "tiktok": {"label": "TikTok", "support": "manual_only", "provider": None},
    "naver_blog": {"label": "네이버 블로그·카페", "support": "manual_only", "provider": None},
    "offline": {"label": "오프라인·팝업", "support": "manual_only", "provider": None},
    "sales": {"label": "판매·매출 데이터", "support": "unsupported", "provider": None},
    # Sources the AE factbook scope names (팩트북 표준 목차 §4) that have no collector yet: a person
    # enters or uploads what they find there.
    "dart": {"label": "DART 공시·감사보고서", "support": "manual_only", "provider": None},
    "tvcf": {"label": "TVCF 광고 아카이브", "support": "manual_only", "provider": None},
    "community": {"label": "커뮤니티 (클리앙·더쿠·네이버 카페 등)", "support": "manual_only", "provider": None},
    "commerce_review": {"label": "커머스 리뷰 (무신사·29CM·네이버쇼핑)", "support": "manual_only", "provider": None},
    "commerce_rank": {"label": "커머스 랭킹", "support": "manual_only", "provider": None},
    "app_review": {"label": "앱스토어·구글플레이 리뷰", "support": "manual_only", "provider": None},
    "report": {"label": "리서치·협회 리포트 (메조미디어·나스미디어·KOSIS)", "support": "manual_only", "provider": None},
    "upload": {"label": "내부 자료 업로드 (패널 조사·트래커·매체 리포트)", "support": "manual_only", "provider": None},
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


def channel_status(provider: Optional[str], configured: bool) -> str:
    if provider is None:
        return "manual_only"
    return "ready" if configured else "key_missing"
