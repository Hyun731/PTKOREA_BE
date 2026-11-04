"""schema.org Product/AggregateRating JSON-LD 추출 — 검색엔진을 위해 대부분의 전자상거래
사이트가 공개하는 표준 포맷(무신사에서 실제로 확인; 다른 플랫폼 모듈은 각자 docstring에
실제로 확인된 것과 확인하지 못한 것(접근 차단)을 구분해 적는다)."""
from __future__ import annotations

import json
import re

LD_JSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def extract_product(html: str, url: str, platform: str) -> dict:
    """못 찾으면(구조가 다르거나 차단 안내 페이지면) access_status="unavailable"로 남긴다."""
    for m in LD_JSON_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "Product":
            continue
        rating = data.get("aggregateRating") or {}
        return {
            "platform": platform, "product_name": data.get("name") or "", "product_url": url,
            "brand_name": (data.get("brand") or {}).get("name"),
            "rating": rating.get("ratingValue"), "rating_scale": rating.get("bestRating") or 5.0,
            "review_count": rating.get("reviewCount"), "access_status": "ok",
        }
    return {"platform": platform, "product_name": "", "product_url": url, "access_status": "unavailable",
           "reason": "상품 정보(JSON-LD)를 찾을 수 없음 — 페이지 구조가 바뀌었거나 접근이 막혔을 수 있음"}
