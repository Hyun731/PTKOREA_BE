"""무신사(MUSINSA) 공개 상품·리뷰 페이지 (Phase 2 커머스 리뷰).

상품 평점·리뷰 수·상품명은 모든 전자상거래 사이트가 검색엔진을 위해 공개하는 표준
schema.org JSON-LD(<script type="application/ld+json">)에서 읽는다. 리뷰 원문·개별 평점·
게시일은 로그인 없이 누구나 보는 공개 리뷰 목록 API에서 읽는다 — 구매자 전용 탭 같은
로그인 전용 리뷰는 다루지 않는다. 봇 차단을 피하려는 쿠키·세션 유지나 재시도는 하지
않는다: 막히면(차단·구조 변경) 그대로 접근 불가로 남긴다.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from integrations.base import ProviderError
from integrations.commerce import schema_org

PLATFORM = "musinsa"
USER_AGENT = "Mozilla/5.0 (compatible; PTK-ResearchBot/0.1; +https://example.invalid/bot)"
SEARCH_URL = "https://www.musinsa.com/search/goods"
PRODUCT_URL = "https://www.musinsa.com/products/{goods_no}"
REVIEW_API = "https://goods.musinsa.com/api2/review/v1/view/list"

PRODUCT_LINK_RE = re.compile(r"/products/(\d+)")
# 체험단·협찬 고지 문구(표시광고법상 리뷰 본문에 필수 고지) — 공개 API에 별도 플래그가 없어 본문에서 찾는다.
SPONSORED_PATTERN = re.compile(r"체험단|협찬|제공\s*받[아은]|원고료|무상\s*제공")


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    r = client.get(url, **kw)
    if r.status_code != 200:
        code = "RATE_LIMITED" if r.status_code == 429 else "SOURCE_UNAVAILABLE"
        raise ProviderError(code, f"무신사 접근 실패 ({r.status_code})", r.status_code)
    return r


def find_product(keyword: str, *, transport: Optional[httpx.BaseTransport] = None) -> Optional[dict]:
    """키워드로 검색해 첫 결과 상품의 번호·URL을 돌려준다, 없으면 None."""
    with httpx.Client(timeout=15.0, follow_redirects=True, transport=transport,
                      headers={"User-Agent": USER_AGENT}) as client:
        r = _get(client, SEARCH_URL, params={"keyword": keyword})
        m = PRODUCT_LINK_RE.search(r.text)
        if not m:
            return None
        goods_no = m.group(1)
        return {"id": goods_no, "url": PRODUCT_URL.format(goods_no=goods_no)}


def parse_product_page(html: str, url: str) -> dict:
    """schema.org JSON-LD에서 상품명·브랜드·평점·리뷰 수를 읽는다. 못 찾으면 접근 불가로 남긴다."""
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


def parse_reviews(payload: dict) -> list[dict]:
    """리뷰 목록 API 응답에서 원문·평점·게시일·체험단 여부를 읽는다."""
    rows = []
    for row in (payload.get("data") or {}).get("list") or []:
        text = (row.get("content") or "").strip()
        if not text:
            continue
        try:
            rating = int(row["grade"]) if row.get("grade") is not None else None
        except (TypeError, ValueError):
            rating = None
        rows.append({"text": text, "rating": rating, "posted_at": (row.get("createDate") or "")[:10],
                     "sponsored": bool(SPONSORED_PATTERN.search(text))})
    return rows


def fetch_reviews(goods_no: str, *, page: int = 0, page_size: int = 20,
                  transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    with httpx.Client(timeout=15.0, transport=transport, headers={"User-Agent": USER_AGENT}) as client:
        try:
            r = _get(client, REVIEW_API, params={"goodsNo": goods_no, "page": page, "pageSize": page_size,
                                                 "sort": "new", "selectedSimilarNo": goods_no})
        except ProviderError:
            return []
        try:
            payload = r.json()
        except ValueError:
            return []
        return parse_reviews(payload)
