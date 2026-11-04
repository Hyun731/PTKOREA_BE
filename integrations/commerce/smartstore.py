"""네이버 스마트스토어 공개 상품·리뷰 페이지 (Phase 2 커머스 리뷰).

실제로 확인한 것: 스마트스토어는 판매자별 하위 경로(smartstore.naver.com/{스토어}/products/
{번호})로 흩어져 있어, 상품명으로 찾으려면 네이버쇼핑 통합검색을 거쳐야 한다. 정직한 봇
식별(USER_AGENT, PTK-ResearchBot)로 그 검색(search.shopping.naver.com)을 요청하면 418
("I'm a teapot", 네이버의 의도적인 차단 응답)로 막힌다. 우회(쿠키·세션 유지, 브라우저
흉내)는 시도하지 않는다 — 막히면 그대로 접근 불가로 남긴다. smartstore.naver.com 루트
자체는 200을 돌려주지만 그건 셀러 로그인 페이지일 뿐, 상품 데이터가 아니다.
확인하지 못한 것: 개별 스토어 상품 페이지 구조(검색이 막혀 실제 상품에 닿을 방법이 없었다).
아래 schema.org 파싱은 통상적인 관례를 따른 추정이며, 검색 경로가 열리면 다시 확인해야
한다. 리뷰 원문 API도 확인하지 못해 fetch_reviews()는 항상 빈 목록.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from integrations.base import ProviderError
from integrations.commerce import schema_org

PLATFORM = "smartstore"
USER_AGENT = "Mozilla/5.0 (compatible; PTK-ResearchBot/0.1; +https://example.invalid/bot)"
SEARCH_URL = "https://search.shopping.naver.com/search/all"
PRODUCT_LINK_RE = re.compile(r"https://smartstore\.naver\.com/([\w.-]+)/products/(\d+)")


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    r = client.get(url, **kw)
    if r.status_code != 200:
        code = "RATE_LIMITED" if r.status_code in (429, 418) else "SOURCE_UNAVAILABLE"
        raise ProviderError(code, f"스마트스토어 접근 실패 ({r.status_code})", r.status_code)
    return r


def find_product(keyword: str, *, transport: Optional[httpx.BaseTransport] = None) -> Optional[dict]:
    """네이버쇼핑 통합검색에서 스마트스토어 상품 링크를 찾는다, 없으면 None."""
    with httpx.Client(timeout=15.0, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        r = _get(client, SEARCH_URL, params={"query": keyword})
        m = PRODUCT_LINK_RE.search(r.text)
        if not m:
            return None
        store, product_id = m.group(1), m.group(2)
        url = f"https://smartstore.naver.com/{store}/products/{product_id}"
        return {"id": f"{store}/{product_id}", "url": url}


def parse_product_page(html: str, url: str) -> dict:
    return schema_org.extract_product(html, url, PLATFORM)


def fetch_product(store_and_id: str, *, transport: Optional[httpx.BaseTransport] = None) -> dict:
    url = f"https://smartstore.naver.com/{store_and_id}"
    with httpx.Client(timeout=15.0, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        try:
            r = _get(client, url)
        except ProviderError as exc:
            return {"platform": PLATFORM, "product_name": "", "product_url": url, "access_status": "unavailable",
                   "reason": exc.message}
        return parse_product_page(r.text, url)


def fetch_reviews(store_and_id: str, *, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """공개 리뷰 API를 확인하지 못했다(검색이 막혀 실제 상품 페이지에 닿지 못함) — 항상 빈 목록."""
    return []
