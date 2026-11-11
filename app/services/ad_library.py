"""경쟁사 포지셔닝(3-5) 보강: 유료 소셜 광고 소재 유형 비중 — Meta 광고 라이브러리 공개 페이지를
시도해 본다(Phase 3-2). 로그인·봇 차단으로 막히면 "접근 불가"로 남긴다 — 사람이 대신 채워 넣는다.

Meta는 자동 접근을 적극적으로 막는다(봇 확인 페이지, 로그인 유도): 이 모듈은 공개 페이지를
한 번 평범하게 요청해 볼 뿐, 그 차단을 우회하려 시도하지 않는다. 막히면 그대로 "unavailable"을
돌려주는 것이 정상 동작이다.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Callable, Optional
from urllib.parse import quote

from core.decimalx import canonical_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact
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


# ---------------------------------------------------------------- P2-9 공개 광고 라이브러리(ScrapeCreators)
# 위의 페이지 직접 요청은 거의 늘 막혀서, 3-5 경쟁사 포지셔닝 항목은 ScrapeCreators의 광고 라이브러리
# 엔드포인트로 소재를 모은다(app.services.research.run_ad_library_item). 모두 공개 정보이고, 소재 카드는
# 후보로만 남는다 — 사람이 채택해야 수치(Fact)도 함께 쓰인다.

AD_CREATIVE_TYPES = ("product", "celebrity", "creator", "discount", "brand_film")
AD_CREATIVE_LABEL = {"product": "제품 중심", "celebrity": "셀럽", "creator": "크리에이터", "discount": "할인·혜택",
                     "brand_film": "브랜드 필름"}
AD_PLATFORM_LABEL = {"meta": "메타(페이스북·인스타그램)", "google": "구글", "tiktok": "틱톡(유럽 공개분)"}
# 유형 비중은 국내 광고만으로 낸다 — 틱톡 공개 광고 라이브러리는 유럽분뿐이라 건수만 남긴다.
SHARE_PLATFORMS = ("meta", "google")
AD_CLASSIFY_SYSTEM = """당신은 브랜드 광고 소재를 유형으로 나누는 리서처입니다. <ads>의 광고마다 type 하나를 고릅니다.
이미지가 붙은 광고는 '(이미지 n)'으로 표시되어 있고, 이미지는 그 순서대로 앞에 붙어 있습니다.
- product: 제품 자체가 주인공(제품 컷·기능·스펙 소개). 사람이 나와도 제품 설명이 중심이면 product.
- celebrity: 연예인·운동선수 등 유명인 모델이 중심.
- creator: 인플루언서·크리에이터의 후기·사용기 말투(#광고, 협찬 표기, 1인칭 체험담).
- discount: 할인·특가·쿠폰·기획전·사은품 등 혜택이 중심.
- brand_film: 브랜드 철학·감성·스토리 영상이나 캠페인 메시지가 중심.
글과 이미지에 보이는 것만으로 판단합니다. 애매하면 가장 크게 보이는 요소를 고릅니다."""
AD_CLASSIFY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ads"],
    "properties": {"ads": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["no", "type"],
        "properties": {"no": {"type": "integer"}, "type": {"type": "string", "enum": list(AD_CREATIVE_TYPES)}}}}},
}
FORMAT_LABEL = {"video": "영상", "image": "이미지", "text": "텍스트", "carousel": "슬라이드", "dpa": "카탈로그",
                "dco": "카탈로그"}


def latin_names(names: list[str]) -> list[str]:
    """메타·틱톡 광고 라이브러리는 영문 이름으로만 찾힌다."""
    return [n for n in names if re.search(r"[A-Za-z]", n)]


def _key(s: str) -> str:
    return re.sub(r"\s|\(주\)|㈜|주식회사|[()]", "", s or "").lower()


def matches(text: str, names: list[str]) -> bool:
    t = _key(text)
    return any(len(_key(n)) >= 2 and _key(n) in t for n in names)


def _page_words(pg: dict) -> str:
    return " ".join(filter(None, (pg.get("name"), pg.get("alias"), pg.get("ig_username"))))


def pick_meta_page(pages: list[dict], names: list[str]) -> Optional[dict]:
    """한국 페이지를 고른다: 나라가 KR이거나 이름·별칭·인스타 계정에 korea/kr이 있는 것, 그다음
    이름이 맞는 인증 페이지 중 좋아요가 많은 것. 이름이 안 맞으면 고르지 않는다."""
    named = [pg for pg in pages if matches(_page_words(pg), names)]
    korean = [pg for pg in named if pg.get("country") == "KR"
              or re.search(r"korea|(^|[^a-z])kr([^a-z]|$)", _page_words(pg).lower())]
    pool = korean or [pg for pg in named if pg.get("verified")] or named
    return max(pool, key=lambda pg: pg.get("likes") or 0) if pool else None


def is_korean_page(pg: dict) -> bool:
    return pg.get("country") == "KR" or bool(re.search(r"korea|(^|[^a-z])kr([^a-z]|$)", _page_words(pg).lower()))


def pick_google_advertisers(rows: list[dict], names: list[str], limit: int = 2) -> list[dict]:
    named = [r for r in rows if matches(r["name"], names) and r.get("region") in ("KR", None)]
    return sorted(named, key=lambda r: -(r.get("ads_estimate") or 0))[:limit]


def in_window(ad: dict, start: date, end: date) -> bool:
    """기간과 하루라도 겹쳐 게재된 광고. 날짜가 없으면 판단하지 않고 남긴다."""
    first, last = ad.get("start"), ad.get("end") or ad.get("start")
    if first and first > end.isoformat():
        return False
    if last and last < start.isoformat():
        return False
    return True


def classify_prompt(entity: str, ads: list[dict], image_no: dict[int, int]) -> str:
    lines = []
    for i, ad in enumerate(ads, start=1):
        fmt = FORMAT_LABEL.get(ad.get("format") or "", ad.get("format") or "")
        img = f" (이미지 {image_no[i]})" if i in image_no else ""
        text = re.sub(r"\s+", " ", ad.get("text") or "").strip()[:300] or "(문구 없음)"
        lines.append(f"{i}. [{AD_PLATFORM_LABEL.get(ad['platform'], ad['platform'])}·{fmt}]{img} {text}")
    return f"<brand>{entity}</brand>\n<ads>\n" + "\n".join(lines) + "\n</ads>"


def type_shares(types: list[str]) -> dict[str, float]:
    n = len(types)
    return {t: round(types.count(t) / n * 100, 1) for t in AD_CREATIVE_TYPES} if n else {}


def ad_fact(*, brand_id: str, entity: str, metric: str, value: Decimal, unit: str, dims: dict, period_start: date,
            period_end: date, measured_at: date, source: str, label: str, url: Optional[str], evidence_id: str) -> Fact:
    dims = {k: str(v) for k, v in sorted(dims.items())}
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(value), "unit": unit,
               "dims": json.dumps(dims, ensure_ascii=False, sort_keys=True), "period": f"{period_start}~{period_end}",
               "measured_at": measured_at.isoformat(), "source": source, "evidence_id": evidence_id}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric, value=value,
                unit=unit, dims=dims, period_start=period_start, period_end=period_end, measured_at=measured_at,
                source=source, evidence_id=evidence_id, url=url, confidence="verified", label=label,
                source_locator=evidence_id)
