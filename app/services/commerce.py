"""커머스 리뷰 데이터 규칙(Phase 2 커머스 리뷰 모듈).

플랫폼 파서(integrations/commerce/*.py)가 공개 페이지에서 읽어낸 원시 값을 저장 가능한 형태로
검증한다. 자동 채택은 없다 — 여기를 통과한 행도 candidate로만 저장되고, 사람이 채택해야 장표에
쓰인다(core/composition/commerce.py).

지켜야 할 규칙 (문서 그대로):
- 평점은 플랫폼, 상품, 리뷰 수, 측정일과 함께만 쓴다. 리뷰 수 없는 평점은 쓰지 않는다.
- 플랫폼이 다른 평점을 평균 내거나 합치지 않는다 — group_key()가 그 단위를 정의하고,
  composition은 이 키로 묶은 행을 다시 묶지 않는다.
- 같은 상품의 다른 옵션·SKU 리뷰를 섞지 않는다 — product_url이 정확한 SKU 식별자다.
- 체험단·협찬 리뷰는 따로 센다(sponsored_count) — 키워드 집계에서 뺀다.
- 키워드마다 원문 1개 이상과 게시일이 있어야 한다. 표본 수와 분류 방법도 함께 적는다.
- 자사 브랜드끼리 평점 순위를 매기지 않는다 — core/quality/qc.py의 기존 규칙(3b, PRD 핵심가치 1)이
  N() 태그된 자사 브랜드명 비교를 이미 막는다; 여기서 새로 만들 규칙은 없다.
"""
from __future__ import annotations

from typing import Optional

PLATFORMS: tuple[str, ...] = ("musinsa", "29cm", "oliveyoung", "smartstore", "coupang")
PLATFORM_LABEL: dict[str, str] = {
    "musinsa": "무신사", "29cm": "29CM", "oliveyoung": "올리브영", "smartstore": "스마트스토어", "coupang": "쿠팡",
}
# 플랫폼마다 만점 기준(모두 5점 만점이지만, 다를 수 있어 파서가 명시하도록 강제한다).
DEFAULT_SCALE: dict[str, float] = {"musinsa": 5.0, "29cm": 5.0, "oliveyoung": 5.0, "smartstore": 5.0, "coupang": 5.0}

SENTIMENTS: tuple[str, ...] = ("positive", "negative")


def group_key(platform: str, product_url: str) -> tuple[str, str]:
    """평점·리뷰 수를 묶거나 비교할 수 있는 가장 작은 단위 — 플랫폼 하나 + 정확한 상품(SKU) 하나.
    이 키가 다르면 절대 같은 축에 합치지 않는다(다른 옵션·다른 플랫폼 숫자를 평균 내지 않음)."""
    return (platform, product_url)


def validate_snapshot(data: dict) -> Optional[str]:
    """이 리뷰 스냅샷을 저장할 수 없는 이유, 문제없으면 None."""
    if data.get("platform") not in PLATFORMS:
        return f"지원하지 않는 플랫폼: {data.get('platform')}"
    if not (data.get("product_name") or "").strip():
        return "상품명이 없음"
    if not (data.get("product_url") or "").strip():
        return "상품 URL이 없음 — 옵션·SKU를 구분할 수 없음"
    if data.get("access_status") == "unavailable":
        return None  # 접근 불가는 그 자체로 유효한 결과 — 평점 없이 저장
    rating, review_count = data.get("rating"), data.get("review_count")
    if rating is not None and not review_count:
        return "리뷰 수 없는 평점은 쓰지 않음"
    if rating is not None:
        scale = data.get("rating_scale") or DEFAULT_SCALE.get(data["platform"], 5.0)
        if not (0 <= rating <= scale):
            return f"평점이 만점({scale}) 범위를 벗어남"
    if review_count is not None and review_count < 0:
        return "리뷰 수가 음수"
    sponsored = data.get("sponsored_count") or 0
    if sponsored < 0:
        return "체험단 리뷰 수가 음수"
    if review_count is not None and sponsored > review_count:
        return "체험단 리뷰 수가 전체 리뷰 수보다 많음"
    if not data.get("measured_at"):
        return "측정일이 없음"
    return None


def validate_keyword(data: dict) -> Optional[str]:
    """이 리뷰 키워드를 저장할 수 없는 이유, 문제없으면 None."""
    if data.get("sentiment") not in SENTIMENTS:
        return "긍정/부정 분류가 없음"
    if not (data.get("keyword") or "").strip():
        return "키워드가 비어 있음"
    quotes = data.get("quotes") or []
    if not quotes:
        return "원문 인용이 없음(최소 1개 필요)"
    for q in quotes:
        if not (q.get("text") or "").strip():
            return "원문 인용 문장이 비어 있음"
        if not q.get("posted_at"):
            return "원문 인용의 게시일이 없음"
    if not data.get("sample_size") or data["sample_size"] < 1:
        return "표본 수가 없음(비율에는 표본 수가 있어야 함)"
    if not (data.get("method") or "").strip():
        return "분류 방법이 없음"
    return None
