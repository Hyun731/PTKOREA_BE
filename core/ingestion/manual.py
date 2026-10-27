"""Manually entered facts (PRD R05 직접 사실 작성, M01, F01).

A person types a value and links it to a source card. It gets the same content-hash ID
scheme as CSV facts and starts as `candidate` until reviewed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from core.decimalx import canonical_decimal, parse_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import MANUAL_METRICS, Fact

UNIT_ALIASES = {"count": "count", "krw": "krw", "percent": "percent", "rank": "rank"}


def make_manual_fact(*, brand_id: str, entity: str, metric: str, value, measured_at: date, source: str,
                     source_id: Optional[str] = None, evidence_id: Optional[str] = None, label: Optional[str] = None,
                     period_start: Optional[date] = None, period_end: Optional[date] = None, url: Optional[str] = None,
                     confidence: str = "verified", status: str = "candidate") -> Fact:
    if metric not in MANUAL_METRICS:
        raise ValueError(f"지원하지 않는 직접 입력 지표 {metric}")
    v = parse_decimal(value) if not isinstance(value, Decimal) else value
    if v is None:
        raise ValueError("값이 비어 있습니다")
    if v < 0:
        raise ValueError("음수 값은 허용되지 않습니다")
    unit = MANUAL_METRICS[metric]
    if unit == "count" and v != v.to_integral_value():
        raise ValueError("건수 지표는 정수여야 합니다")
    start = period_start or measured_at
    end = period_end or measured_at
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(v), "unit": unit,
               "period": f"{start}~{end}", "measured_at": measured_at.isoformat(), "source": source,
               "source_id": source_id, "evidence_id": evidence_id, "label": label}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric, value=v,
                unit=unit, dims={}, period_start=start, period_end=end, measured_at=measured_at, source=source,
                source_id=source_id, evidence_id=evidence_id, url=url, confidence=confidence,
                verification_status=status, label=label, source_locator=evidence_id)
