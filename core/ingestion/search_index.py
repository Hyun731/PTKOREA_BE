"""search_group_sum / search_index_monthly Facts built from Naver DataLab ratios (R05 자동 수집).

Same shape and content-hash scheme as a CSV-imported search-index row (core/ingestion/csv_import.py)
so the metrics engine (core/metrics/engine.py) treats either source identically; only the
`source`/`confidence` differ.
"""
from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal
from typing import Optional

from core.decimalx import canonical_decimal, parse_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

SOURCE_LABEL = "네이버 데이터랩 검색어트렌드"


def _canonical_dims(dims: dict) -> str:
    return json.dumps(dims, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _payload(brand_id: str, entity: str, metric: str, value: Decimal, dims: dict, period_start: date,
            period_end: date, measured_at: date) -> dict:
    return {"brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(value), "unit": "index",
            "dims": _canonical_dims(dims), "period": f"{period_start}~{period_end}", "measured_at": measured_at.isoformat(),
            "source": SOURCE_LABEL, "url": None, "method": None, "confidence": "verified", "source_record_key": None}


def _with_cat(dims: dict, cat: Optional[str]) -> dict:
    """Combination-keyword sets ('브랜드+카테고리', 2-8c) carry their category; brand-name sets don't —
    so existing brand-name facts keep exactly the same dims and content hash. Only window sums take a
    category: the monthly series (2-8b) is the brand-name set alone, one series per (brand, seg)."""
    return {**dims, "cat": cat} if cat else dims


def monthly_fact(*, brand_id: str, entity: str, month: str, ratio: float, seg: str, scale_id: str,
                 measured_at: date) -> Fact:
    start, end = _month_bounds(month)
    value = parse_decimal(str(round(ratio, 4)))
    dims = {"month": month, "seg": seg, "scale_id": scale_id}
    payload = _payload(brand_id, entity, "search_index_monthly", value, dims, start, end, measured_at)
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric="search_index_monthly",
               value=value, unit="index", dims=dims, period_start=start, period_end=end, measured_at=measured_at,
               source=SOURCE_LABEL, confidence="verified")


def window_sum_fact(*, brand_id: str, entity: str, window_label: str, total: Decimal, seg: str, scale_id: str,
                    period_start: date, period_end: date, measured_at: date, cat: Optional[str] = None) -> Fact:
    dims = _with_cat({"window": window_label, "seg": seg, "scale_id": scale_id}, cat)
    payload = _payload(brand_id, entity, "search_group_sum", total, dims, period_start, period_end, measured_at)
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric="search_group_sum",
               value=total, unit="index", dims=dims, period_start=period_start, period_end=period_end,
               measured_at=measured_at, source=SOURCE_LABEL, confidence="verified")


# 네이버 데이터랩 검색어트렌드 연령 코드 → (최소, 최대) 나이. 11은 60세 이상.
NAVER_AGE_BANDS: dict[str, tuple[int, int]] = {
    "1": (0, 12), "2": (13, 18), "3": (19, 24), "4": (25, 29), "5": (30, 34), "6": (35, 39),
    "7": (40, 44), "8": (45, 49), "9": (50, 54), "10": (55, 59), "11": (60, 200),
}
MAX_COMBO_KEYWORDS = 20  # DataLab: keywords per group


def naver_target_filter(age_min: Optional[int], age_max: Optional[int], gender: str) -> Optional[dict]:
    """Brand.target → DataLab filter {"ages": [...], "gender": "f"|"m"}; None when the target narrows nothing
    (no age range and all genders) — then there is no '키 타겟' set to compare with '전체'.
    Every age band that overlaps the range is included (25~34 → 25-29, 30-34)."""
    out: dict = {}
    if age_min is not None or age_max is not None:
        lo, hi = age_min if age_min is not None else 0, age_max if age_max is not None else 200
        ages = [code for code, (a, b) in NAVER_AGE_BANDS.items() if a <= hi and b >= lo]
        if ages and len(ages) < len(NAVER_AGE_BANDS):
            out["ages"] = ages
    if gender in ("female", "male"):
        out["gender"] = "f" if gender == "female" else "m"
    return out or None


def combo_keywords(names: list[str], category: str) -> list[str]:
    """'브랜드+카테고리' search terms for one entity: each name with and without a space
    ('샘소나이트 캐리어', '샘소나이트캐리어'), de-duplicated, at most 20 (DataLab limit)."""
    out: list[str] = []
    for n in names:
        for kw in (f"{n} {category}", f"{n}{category}"):
            if kw not in out:
                out.append(kw)
    return out[:MAX_COMBO_KEYWORDS]
