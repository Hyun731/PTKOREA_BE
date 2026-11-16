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


# ---------------------------------------------------------------- 브랜드 상품 목록·찜 수·연령별 랭킹
# 모두 로그인 없이 무신사 웹이 그대로 부르는 공개 목록 API다(2026-11 확인). 쿠키·세션을 쓰지 않는다.

PLP_API = "https://api.musinsa.com/api2/dp/v1/plp/goods"
LIKE_API = "https://like.musinsa.com/like/api/v2/liketypes/goods/counts"
RANK_PAN_API = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking"
RANK_SECTION_API = "https://api.musinsa.com/api2/hm/web/v5/pans/ranking/sections/{section}"
RANK_SECTION_ALL = "199"  # 랭킹 '전체' 탭(신상·급상승 같은 테마 탭이 아님)
RANK_KEY_RE = re.compile(r"musinsa_" + RANK_SECTION_ALL + r"_(\d{3}|\d{6})$")
# 무신사 연령 필터(값 그대로) → 장표 라벨
AGE_BANDS = {"AGE_BAND_ALL": "전체", "AGE_BAND_MINOR": "19세 이하", "AGE_BAND_20": "20~24세", "AGE_BAND_25": "25~29세",
             "AGE_BAND_30": "30~34세", "AGE_BAND_35": "35~39세", "AGE_BAND_40": "40세 이상"}
AGE_BAND_RANGE = {"AGE_BAND_MINOR": (0, 19), "AGE_BAND_20": (20, 24), "AGE_BAND_25": (25, 29),
                  "AGE_BAND_30": (30, 34), "AGE_BAND_35": (35, 39), "AGE_BAND_40": (40, 200)}


def _client(transport: Optional[httpx.BaseTransport] = None) -> httpx.Client:
    return httpx.Client(timeout=15.0, follow_redirects=True, transport=transport, headers={"User-Agent": USER_AGENT})


def parse_plp(payload: dict) -> list[dict]:
    """상품 목록 API 응답 → 상품 행. reviewScore는 100점 만점(평점 4.9 = 98)이라 5점 만점으로 바꾼다."""
    rows = []
    for g in (payload.get("data") or {}).get("list") or []:
        if not g.get("goodsNo"):
            continue
        score = g.get("reviewScore")
        rows.append({"id": str(g["goodsNo"]), "name": g.get("goodsName") or "", "brand": g.get("brand") or "",
                     "brand_name": g.get("brandName") or "", "review_count": int(g.get("reviewCount") or 0),
                     "rating": round(score / 20, 2) if isinstance(score, (int, float)) and score else None,
                     "url": g.get("goodsLinkUrl") or PRODUCT_URL.format(goods_no=g["goodsNo"])})
    return rows


def search_goods(keyword: str, *, size: int = 60, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """검색 결과 상품(인기순) — 브랜드를 찾는 데 쓴다."""
    with _client(transport) as c:
        r = _get(c, PLP_API, params={"gf": "A", "keyword": keyword, "sortCode": "POPULAR", "page": 1, "size": size,
                                     "caller": "SEARCH"})
        return parse_plp(r.json())


def brand_goods(brand: str, *, size: int = 60, transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """브랜드 상품을 후기 많은 순으로(무신사 '후기순' 정렬 그대로)."""
    with _client(transport) as c:
        r = _get(c, PLP_API, params={"brand": brand, "sortCode": "REVIEW", "page": 1, "size": size, "caller": "BRAND"})
        return parse_plp(r.json())


def like_counts(goods_nos: list[str], *, transport: Optional[httpx.BaseTransport] = None) -> dict[str, int]:
    """상품별 좋아요(찜) 수."""
    if not goods_nos:
        return {}
    with _client(transport) as c:
        r = c.post(LIKE_API, json={"relationIds": [str(g) for g in goods_nos]})
        if r.status_code != 200:
            raise ProviderError("SOURCE_UNAVAILABLE", f"무신사 좋아요 수 접근 실패 ({r.status_code})", r.status_code)
        items = (((r.json().get("data") or {}).get("contents") or {}).get("items")) or []
        return {str(i["relationId"]): int(i.get("count") or 0) for i in items if i.get("relationId")}


def parse_rank_categories(payload: dict) -> dict[str, str]:
    """랭킹 화면 정의에서 '전체' 탭의 카테고리 {라벨: 6자리 코드}. 라벨이 겹치면(예: '가방'은 대분류 004와
    스포츠/레저 아래 017025) 대분류를 먼저, 그다음 먼저 나온 것. 대분류 '004'는 요청 코드 '004000'으로 쓴다."""
    out: dict[str, str] = {}
    top: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            m = RANK_KEY_RE.match(str(o.get("key") or ""))
            label = o.get("text")
            label = label.get("text") if isinstance(label, dict) else label
            if m and isinstance(label, str) and label != "전체":
                code = m.group(1)
                if len(code) == 3:
                    out[label] = code + "000"
                    top.add(label)
                elif label not in top:
                    out.setdefault(label, code)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(payload)
    return out


def rank_categories(*, transport: Optional[httpx.BaseTransport] = None) -> dict[str, str]:
    with _client(transport) as c:
        r = _get(c, RANK_PAN_API, params={"storeCode": "musinsa"})
        return parse_rank_categories(r.json())


def _dig(o, *keys):
    for k in keys:
        if not isinstance(o, dict):
            return None
        o = o.get(k)
    return o


def parse_ranking(payload: dict) -> list[dict]:
    """랭킹 섹션 응답 → [{rank, id, name, brand, brand_name}] (순위 오름차순)."""
    rows = []
    for m in (payload.get("data") or {}).get("modules") or []:
        for it in m.get("items") or []:
            if it.get("type") != "PRODUCT_COLUMN":
                continue
            rank = _dig(it, "image", "rank")
            info = it.get("info") or {}
            brand = (_dig(info, "onClickBrandName", "eventLog", "ga4", "payload", "brand_id")
                     or _dig(info, "onClickBrandName", "eventLog", "amplitude", "payload", "brand_id") or "")
            if not isinstance(rank, int) or not it.get("id"):
                continue
            rows.append({"rank": rank, "id": str(it["id"]), "name": info.get("productName") or "", "brand": brand,
                         "brand_name": info.get("brandName") or ""})
    return sorted(rows, key=lambda r: r["rank"])


def ranking(category_code: str, age_band: str = "AGE_BAND_ALL", period: str = "MONTHLY", *,
            transport: Optional[httpx.BaseTransport] = None) -> list[dict]:
    """카테고리 판매 랭킹(상위 약 100개) — 연령대·기간 필터는 무신사 화면의 필터 그대로."""
    with _client(transport) as c:
        r = _get(c, RANK_SECTION_API.format(section=RANK_SECTION_ALL),
                 params={"storeCode": "musinsa", "categoryCode": category_code, "gf": "A", "ageBand": age_band,
                         "period": period})
        return parse_ranking(r.json())
