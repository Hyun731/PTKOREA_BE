"""경쟁사 포지셔닝(3-5) 보강: 유료 소셜 광고 소재 유형 비중 — Meta 광고 라이브러리 공개 페이지를
시도해 본다(Phase 3-2). 로그인·봇 차단으로 막히면 "접근 불가"로 남긴다 — 사람이 대신 채워 넣는다.

Meta는 자동 접근을 적극적으로 막는다(봇 확인 페이지, 로그인 유도): 이 모듈은 공개 페이지를
한 번 평범하게 요청해 볼 뿐, 그 차단을 우회하려 시도하지 않는다. 막히면 그대로 "unavailable"을
돌려주는 것이 정상 동작이다.
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import quote

from integrations.base import ProviderError
from integrations.fetch.page import Page, fetch_page

AD_LIBRARY_URL = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                  "&country={country}&q={q}&search_type=keyword_unordered")

CREATIVE_TYPES = ("review", "influencer", "product")
CREATIVE_TYPE_LABEL = {"review": "실사용 후기형", "influencer": "인플루언서형", "product": "제품컷형"}

BLOCKED_MARKERS = ("log in to continue", "로그인", "checkpoint", "security check", "을(를) 사용할 수 없습니다")

MIX_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ad_count", "review", "influencer", "product"],
    "properties": {"ad_count": {"type": "integer", "minimum": 0}, "review": {"type": "integer", "minimum": 0},
                   "influencer": {"type": "integer", "minimum": 0}, "product": {"type": "integer", "minimum": 0}},
}
MIX_SYSTEM = """당신은 광고 소재를 분류하는 보조입니다. <page>는 Meta 광고 라이브러리에서 가져온 광고 목록 페이지입니다.
눈에 보이는 광고 소재마다 다음 세 유형 중 하나로 분류해 유형별 개수를 셉니다.
- review(실사용 후기형): 실제 사용 장면·후기 말투·소비자 인터뷰.
- influencer(인플루언서형): 유명인·크리에이터가 등장해 소개.
- product(제품컷형): 제품 단독 이미지·스펙·가격 중심, 사람 없음.
ad_count는 분류한 전체 광고 수(= review+influencer+product). 광고 소재가 보이지 않으면 모두 0으로 둡니다."""

# Test seams, matching the STRUCTURED-list indirection used across app/services/*.py.
FETCH_PAGE: list[Callable[..., Page]] = []
STRUCTURED: list[Callable] = []


def _fetch_page() -> Callable[..., Page]:
    if not FETCH_PAGE:
        FETCH_PAGE.append(fetch_page)
    return FETCH_PAGE[0]


def _structured() -> Callable:
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def _looks_blocked(page: Page) -> bool:
    text = page.text or ""
    if len(text) < 200:
        return True
    low = text.lower()
    return any(marker in low or marker in text for marker in BLOCKED_MARKERS)


def fetch_ad_mix(entity: str, country: str = "KR") -> dict:
    """{"status": "ok", "mix": {...}, "ad_count": n, "url": ...} 또는
    {"status": "unavailable", "reason": "...", "url": ...}."""
    url = AD_LIBRARY_URL.format(country=country, q=quote(entity))
    try:
        page = _fetch_page()(url)
    except ProviderError as exc:
        return {"status": "unavailable", "reason": f"접근 불가 — {exc.message}", "url": url}
    if _looks_blocked(page):
        return {"status": "unavailable", "reason": "접근 불가 — 로그인 또는 봇 확인 페이지로 막힘", "url": url}
    data = _structured()(MIX_SYSTEM, f"<page>\n{page.text[:8000]}\n</page>", MIX_SCHEMA, max_tokens=200).data
    total = data["review"] + data["influencer"] + data["product"]
    if total == 0:
        return {"status": "unavailable", "reason": "접근 불가 — 페이지에서 광고 소재를 찾지 못함", "url": url}
    mix = {k: round(data[k] / total * 100) for k in CREATIVE_TYPES}
    return {"status": "ok", "mix": mix, "ad_count": data["ad_count"], "url": url}
