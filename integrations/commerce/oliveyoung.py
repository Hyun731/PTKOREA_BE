"""올리브영(oliveyoung.co.kr) 공개 상품·리뷰 페이지 (Phase 2 커머스 리뷰).

실제로 확인한 것: 정직한 봇 식별(USER_AGENT, PTK-ResearchBot) 요청은 메인 페이지를 포함한
모든 경로에서 Cloudflare의 "Attention Required" 봇 차단 페이지(403)로 막힌다 — 엣지(CDN)
단에서 걸러져 특정 엔드포인트만 피해 갈 방법이 없다. 우회(쿠키·세션 유지, 브라우저 흉내)는
시도하지 않는다 — 막히면 그대로 접근 불가로 남긴다.
확인하지 못한 것: 실제 상품·리뷰 페이지 구조. 아래 URL 패턴과 schema.org 파싱은 통상적인
관례를 따른 추정이며, 접근이 가능해지면 다시 확인해야 한다. 리뷰 원문 API는 사이트 전체가
막혀 있어 역공학 자체가 불가능해 만들지 않았다 — fetch_reviews()는 항상 빈 목록.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from integrations.base import ProviderError
from integrations.commerce import schema_org

PLATFORM = "oliveyoung"
USER_AGENT = "Mozilla/5.0 (compatible; PTK-ResearchBot/0.1; +https://example.invalid/bot)"
SEARCH_URL = "https://www.oliveyoung.co.kr/store/search/getSearchMain.do"
PRODUCT_URL = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"

PRODUCT_LINK_RE = re.compile(r"goodsNo=([A-Za-z0-9]+)")


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    r = client.get(url, **kw)
    if r.status_code != 200:
        code = "RATE_LIMITED" if r.status_code == 429 else "SOURCE_UNAVAILABLE"
        raise ProviderError(code, f"올리브영 접근 실패 ({r.status_code})", r.status_code)
    return r


def find_product(keyword: str, *, transport: Optional[httpx.BaseTransport] = None) -> Optional[dict]:
    """키워드로 검색해 첫 결과 상품의 번호·URL을 돌려준다, 없으면 None."""
    with httpx.Client(timeout=15.0, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        r = _get(client, SEARCH_URL, params={"query": keyword})
        m = PRODUCT_LINK_RE.search(r.text)
        if not m:
            return None
        goods_no = m.group(1)
        return {"id": goods_no, "url": PRODUCT_URL.format(goods_no=goods_no)}


def parse_product_page(html: str, url: str) -> dict:
    return schema_org.extract_product(html, url, PLATFORM)


def fetch_product(goods_no: str, *, transport: Optional[httpx.BaseTransport] = None) -> dict:
    url = PRODUCT_URL.format(goods_no=goods_no)
    with httpx.Client(timeout=15.0, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        try:
            r = _get(client, url)
        except ProviderError as exc:
            return {"platform": PLATFORM, "product_name": "", "product_url": url, "access_status": "unavailable",
                   "reason": exc.message}
        return parse_product_page(r.text, url)


def fetch_reviews(goods_no: str, *, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """공개 리뷰 API를 확인하지 못했다(사이트 전체가 봇 차단) — 항상 빈 목록."""
    return []
