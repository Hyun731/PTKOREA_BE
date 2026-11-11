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
     "data": "네이버 데이터랩 검색어트렌드(브랜드명·브랜드+카테고리·키 타겟 연령·성별, 자동) 또는 보유한 검색 지수 CSV",
     "default_window": "9M (+12M 비교 창)"},
    {"id": "influencer", "label": "인플루언서", "templates": ["3-1"],
     "data": "공개 게시물 관측값(ScrapeCreators) 또는 posts CSV", "default_window": "프로젝트 기간"},
    {"id": "campaign", "label": "캠페인 사례", "templates": ["C1", "C2"],
     "data": "기사·공식 자료·게시물 URL + 이미지 + 근거 문장", "default_window": "사용자 지정"},
    {"id": "market", "label": "시장·타겟", "templates": ["M1"],
     "data": "공식 보고서·통계의 확인된 사실", "default_window": "사용자 지정"},
    {"id": "market_kpi", "label": "업종 KPI", "templates": ["M2"],
     "data": "공식 통계·공시의 업종 지표(자사·경쟁사 최근 3년)", "default_window": "최근 3년"},
    {"id": "search_trend", "label": "검색 추이(Google Trends)", "templates": ["TR1"],
     "data": "Google Trends 공개 경로 — 카테고리·브랜드 키워드 상대 지수(0~100)·연관 검색어", "default_window": "최근 12개월"},
    {"id": "commerce_review", "label": "커머스 리뷰", "templates": ["CM1", "CM2"],
     "data": "판매 플랫폼 공개 리뷰(무신사·29CM·올리브영·스마트스토어·쿠팡 자동 시도) — 대표 상품 평점·"
             "리뷰 수·긍정부정 키워드. 무신사 외에는 봇 차단으로 접근 불가가 흔함",
     "default_window": "최신 수집 시점"},
    {"id": "voc", "label": "소비자 원문(VOC)", "templates": ["5-1", "5-2"],
     "data": "카페·블로그·커뮤니티 공개 글(Perplexity 사이트 검색) + X·Threads 공개 게시물(ScrapeCreators 키워드 검색) — "
             "AI 감성·주제·인식 경로 분류",
     "default_window": "24M"},
    {"id": "recap", "label": "Recap", "templates": ["5-recap"], "data": "본문 Finding 요약", "default_window": "-"},
    {"id": "appendix", "label": "출처 표", "templates": ["A-source"], "data": "사용 자료 출처", "default_window": "-"},
]
FRAMES = ["cover", "index", "divider", "end"]
# Search-index slides (2-8a~d) are on by default (P2-1): Naver DataLab collects all four sets —
# brand name, '브랜드+카테고리' combos and the key target's age/gender — so none is CSV-only any more.
# 1-1 (브랜드·카테고리·타겟 매핑) needs no collector — it reads straight from the project's own
# brand/category/target config — so it is on by default for every project, unlike the search slides.
# 1-6 (캠페인 매트릭스) reuses already-collected, already-accepted campaign materials (same
# prerequisite C1/C2 already have), degrading to needs_input like they do until some are
# AI-tagged with a target_segment — on by default for the same reason.
# 2-1 (채널 인벤토리) is opt-in like the search slides: it needs Brand.official_profiles set
# explicitly (which handle is the brand's own account), not something every project has.
DEFAULT_SLIDES = ["cover", "index", "divider", "1-1", "1-6", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1", "C2", "M1",
                 "5-recap", "A-source", "end"]
# The synthetic sample ships its own search CSV, so it keeps the search slides on.
SAMPLE_SLIDES = ["cover", "index", "divider", "1-1", "1-6", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1", "5-recap",
                 "A-source", "end"]

# Channel support must match what can actually be collected (MVP_SITE_REVIEW 6).
CHANNELS = {
    # Full own-account history (2-1 채널 인벤토리), not the single-post/hashtag-discovery
    # channels below. Needs the brand's handle in Brand.official_profiles.
    "instagram_owned": {"label": "Instagram 공식 계정 전체 게시물", "support": "auto", "provider": "scrapecreators"},
    "youtube_owned": {"label": "YouTube 공식 채널 전체 영상", "support": "auto", "provider": "scrapecreators"},
    # 2-8a~d 모두: 브랜드명(seg=all)·브랜드+카테고리(cat)·키 타겟 연령·성별(seg=T) 세트를 데이터랩으로.
    "search_naver": {"label": "네이버 데이터랩 검색어트렌드 (브랜드명·카테고리 조합어·키 타겟)", "support": "auto",
                     "provider": "naver"},
    "search_csv": {"label": "검색 지수 CSV (보유 자료)", "support": "manual_only", "provider": None},
    # Phase 3-4: Google Trends 공개 경로 — 봇 차단으로 자주 막힌다(그러면 "수집 필요"로 조용히 빠짐).
    "google_trends": {"label": "Google Trends (카테고리·브랜드 키워드 월별 추이)", "support": "auto", "provider": "google_trends"},
    "web": {"label": "웹 기사·공식 자료", "support": "auto", "provider": "perplexity"},
    "instagram": {"label": "Instagram 공개 게시물", "support": "auto", "provider": "scrapecreators"},
    "youtube": {"label": "YouTube 공개 영상", "support": "auto", "provider": "scrapecreators"},
    "tiktok": {"label": "TikTok", "support": "manual_only", "provider": None},
    "naver_blog": {"label": "네이버 블로그·카페·티스토리·다음 카페", "support": "auto", "provider": "perplexity"},
    "offline": {"label": "오프라인·팝업", "support": "manual_only", "provider": None},
    "sales": {"label": "판매·매출 데이터", "support": "unsupported", "provider": None},
    # Sources the AE factbook scope names (팩트북 표준 목차 §4) that have no collector yet: a person
    # enters or uploads what they find there.
    "dart": {"label": "DART 공시·감사보고서", "support": "manual_only", "provider": None},
    "tvcf": {"label": "TVCF 광고 아카이브", "support": "manual_only", "provider": None},
    "community": {"label": "커뮤니티 (디시인사이드·에펨코리아·더쿠·루리웹·클리앙·오늘의유머·아카라이브·뽐뿌)",
                  "support": "auto", "provider": "perplexity"},
    # 피드백 #5(SNS 네이티브 검색): 검색 결과 자체에 본문이 있어 커뮤니티처럼 사이트 지정 웹검색이
    # 아니라 ScrapeCreators의 키워드 검색 API를 직접 쓴다. 페이스북은 문서화된 게시물 검색이 없어 뺐다.
    "x_search": {"label": "X(트위터) 공개 게시물 검색", "support": "auto", "provider": "scrapecreators"},
    "threads_search": {"label": "Threads 공개 게시물 검색", "support": "auto", "provider": "scrapecreators"},
    # Phase 2: 무신사·29CM·올리브영·스마트스토어·쿠팡 모두 공개 페이지 자동 수집을 시도한다.
    # 무신사만 정직한 봇 식별 요청을 허용하고, 나머지는 봇 차단(Cloudflare·Akamai 등)으로
    # 접근 불가가 흔하다 — 우회 없이 "접근 불가"로 남긴다.
    "commerce_review": {"label": "커머스 리뷰 (무신사·29CM·올리브영·스마트스토어·쿠팡 자동 시도)",
                        "support": "auto", "provider": "commerce"},
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
