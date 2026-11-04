"""Google Trends 월별 상대 지수 Fact (Phase 3-4 검색 추이). search_index.py(네이버)와 같은 content-hash
방식이지만, 지수가 서로 다른 출처라 다른 metric 이름을 쓴다 — 한 축으로 섞지 않는다.
"""
from __future__ import annotations

import calendar
from datetime import date

from core.decimalx import parse_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

SOURCE_LABEL = "Google Trends"


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def trends_monthly_fact(*, brand_id: str, entity: str, month: str, index: float, measured_at: date) -> Fact:
    """entity: the keyword this point is for (a brand name or a category string)."""
    start, end = _month_bounds(month)
    value = parse_decimal(str(round(index, 2)))
    dims = {"month": month}
    payload = {"brand": brand_id, "entity": entity, "metric": "trends_index_monthly", "value": str(value),
              "unit": "index", "dims": dims, "period": f"{start}~{end}", "measured_at": measured_at.isoformat(),
              "source": SOURCE_LABEL, "url": None, "method": None, "confidence": "verified", "source_record_key": None}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity,
               metric="trends_index_monthly", value=value, unit="index", dims=dims, period_start=start,
               period_end=end, measured_at=measured_at, source=SOURCE_LABEL, confidence="verified")
