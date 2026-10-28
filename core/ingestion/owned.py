"""owned_* Facts built from a brand's own Instagram/YouTube feed (02_보고서_표준목차_장표명세.md §2-1).

Same content-hash Fact shape as csv_import.py / search_index.py; these never go through the
metrics engine's share/rank formulas (core/metrics/engine.py) — 2-1 is a single-brand
descriptive snapshot, not a competitive comparison, so a plain Fact list is enough.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from core.decimalx import canonical_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

SOURCE_LABEL = {"instagram": "Instagram 공개 프로필(ScrapeCreators)", "youtube": "YouTube 채널(ScrapeCreators)"}


def _canonical_dims(dims: dict) -> str:
    return json.dumps(dims, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def owned_fact(*, brand_id: str, entity: str, metric: str, value: Decimal, channel: str, period_start: date,
              period_end: date, measured_at: date, label: str, extra_dims: dict | None = None) -> Fact:
    dims = {"channel": channel, **(extra_dims or {})}
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(value), "unit": "count",
              "dims": _canonical_dims(dims), "period": f"{period_start}~{period_end}", "measured_at": measured_at.isoformat(),
              "source": SOURCE_LABEL[channel], "url": None, "method": None, "confidence": "verified",
              "source_record_key": None}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric, value=value,
               unit="count", dims=dims, period_start=period_start, period_end=period_end, measured_at=measured_at,
               source=SOURCE_LABEL[channel], confidence="verified", label=label)


def monthly_post_count_fact(*, brand_id: str, entity: str, channel: str, month: str, count: int,
                            measured_at: date) -> Fact:
    """owned_posts_by_month — one row per (channel, month) in the item period, zero included (a
    counted zero is a real observation; 2-2's gap analysis depends on seeing the zero months,
    not just the months that happened to have a post)."""
    import calendar

    y, m = map(int, month.split("-"))
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    dims = {"channel": channel, "month": month}
    payload = {"brand": brand_id, "entity": entity, "metric": "owned_posts_by_month", "value": canonical_decimal(Decimal(count)),
              "unit": "count", "dims": _canonical_dims(dims), "period": f"{start}~{end}", "measured_at": measured_at.isoformat(),
              "source": SOURCE_LABEL[channel], "url": None, "method": None, "confidence": "verified",
              "source_record_key": None}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric="owned_posts_by_month",
               value=Decimal(count), unit="count", dims=dims, period_start=start, period_end=end, measured_at=measured_at,
               source=SOURCE_LABEL[channel], confidence="verified", label=f"{'IG' if channel == 'instagram' else 'YT'} 월별 게시 수")
