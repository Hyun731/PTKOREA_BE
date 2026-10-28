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
                    period_start: date, period_end: date, measured_at: date) -> Fact:
    dims = {"window": window_label, "seg": seg, "scale_id": scale_id}
    payload = _payload(brand_id, entity, "search_group_sum", total, dims, period_start, period_end, measured_at)
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric="search_group_sum",
               value=total, unit="index", dims=dims, period_start=period_start, period_end=period_end,
               measured_at=measured_at, source=SOURCE_LABEL, confidence="verified")
