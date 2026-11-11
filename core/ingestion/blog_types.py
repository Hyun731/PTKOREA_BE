"""블로그 문서 유형 (P2-5): 검색어별 네이버 블로그 상위 글이 실사용 후기인지, 협찬·쇼핑 제휴·홍보 글인지.

- blog_type_share: 검색어 하나의 블로그 정확도순 상위 n건 중 유형별 비중(%). dims: keyword, type, n.
  다섯 유형을 모두(0% 포함) 남겨 누적 막대가 100%가 되게 한다. 근거 글 주소는 source_locator(JSON 목록).
- disclosure_markers(): 글에 적힌 대가 표시·제휴 링크 문구. AI 분류에 힌트로 주고, 소비자 원문의 협찬·
  제휴 판정(P2-7)에도 같이 쓴다. 문구가 없다고 실사용이라는 뜻은 아니다.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

BLOG_TYPES = ("real_use", "sponsored", "shopping_affiliate", "promo_template", "other")
TYPE_LABEL = {"real_use": "실사용 후기", "sponsored": "협찬·체험단", "shopping_affiliate": "쇼핑·제휴",
              "promo_template": "홍보 템플릿", "other": "기타"}
SOURCE_LABEL = "네이버 블로그 검색 상위 글(AI 분류)"
METHOD = "네이버 블로그 정확도순 상위 글을 AI가 유형별로 분류(대가 표시·제휴 링크 문구 참고), 비중 = 유형 글 수 ÷ 분류한 글 수"

SPONSORED = re.compile(
    r"원고료|소정의|협찬|체험단|광고\s*포함|유료\s*광고|#\s*광고|(제품|상품|서비스)[을를]?\s*(무상\s*으로\s*|무료\s*로\s*)?"
    r"(제공|지원)\s*받|(업체|브랜드|회사)\s*(로|으로)부터|지원\s*받아\s*작성|리뷰어\s*(로|에)\s*선정")
AFFILIATE = re.compile(
    r"쿠팡\s*파트너스|파트너스\s*활동|수수료를?\s*(제공|지급)\s*받|제휴\s*마케팅|어필리에이트|affiliate|link\.coupang\.com|"
    r"coupa\.ng|구매하고\s*더\s*많은\s*혜택|최저가\s*(바로\s*)?(보기|확인|링크)|구매\s*링크|할인\s*링크|"
    r"네이버\s*쇼핑\s*커넥트|쇼핑\s*커넥트|알리\s*익스프레스\s*어필리", re.IGNORECASE)


def disclosure_markers(text: str) -> list[str]:
    """글에 적힌 표시 문구 종류: 'sponsored'(대가 표시), 'affiliate'(제휴 링크·수수료)."""
    out = []
    if SPONSORED.search(text or ""):
        out.append("sponsored")
    if AFFILIATE.search(text or ""):
        out.append("affiliate")
    return out


def _pct(part: int, whole: int) -> Decimal:
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def share_facts(*, brand_id: str, entity: str, keyword: str, docs: list[dict], measured_at: date,
                min_n: int) -> list[Fact]:
    """docs: [{"url", "type"}] (분류된 글만). 글이 min_n건보다 적으면 비중을 만들지 않는다."""
    docs = [d for d in docs if d.get("type") in BLOG_TYPES]
    n = len(docs)
    if n < min_n or n == 0:
        return []
    out = []
    for t in BLOG_TYPES:
        urls = [d["url"] for d in docs if d["type"] == t]
        value = _pct(len(urls), n)
        dims = {"keyword": keyword, "type": t, "n": str(n)}
        payload = {"brand": brand_id, "entity": entity, "metric": "blog_type_share", "value": str(value),
                   "unit": "percent", "dims": json.dumps(dims, ensure_ascii=False, sort_keys=True),
                   "period": f"{measured_at}~{measured_at}", "measured_at": measured_at.isoformat(), "source": SOURCE_LABEL}
        h = content_hash(payload)
        out.append(Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity,
                        metric="blog_type_share", value=value, unit="percent", dims=dict(sorted(dims.items())),
                        period_start=measured_at, period_end=measured_at, measured_at=measured_at, source=SOURCE_LABEL,
                        method=METHOD, confidence="verified", source_locator=json.dumps(urls, ensure_ascii=False),
                        label=f"'{keyword}' 블로그 상위 {n}건 중 {TYPE_LABEL[t]}"))
    return out
