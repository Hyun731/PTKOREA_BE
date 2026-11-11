"""언급량 Fact (P2-4): 네이버 검색 API(블로그·카페글·뉴스·지식iN)의 검색 결과 문서 수.

- mention_total: 검색어 하나의 `total` — 지금까지 쌓인 검색 결과 문서 수(누적)다. **검색량이 아니다.**
  dims: channel(blog·cafe·news·kin), keyword_group(brand = 브랜드명, brand+{제품군} = 조합어), keyword(실제 검색어).
  기간은 수집일 하루(measured_at)로 둔다 — 누적값이라 조사 기간과 맞출 수 없다.
- mention_monthly: 최근 몇 달의 달별 문서 수. 날짜가 있는 블로그·뉴스만, 날짜순 결과를 넘겨 가며 센다.
  검색 API는 한 검색어에 1,000건까지만 넘겨 볼 수 있어, 그 한도에 걸려 달 초까지 닿지 못한 달에는
  partial=1을 붙인다(그 달 숫자는 '적어도 이만큼'이다).

장표·화면에는 "검색 결과 문서 수(누적)", "월별 문서 수"로만 쓴다(QC OVERCLAIMS 참고).
"""
from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from core.decimalx import canonical_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

# 네이버 검색 API 종류 → Fact의 channel 값
CHANNEL_OF_KIND = {"blog": "blog", "cafearticle": "cafe", "news": "news", "kin": "kin"}
CHANNEL_LABEL = {"blog": "블로그", "cafe": "카페글", "news": "뉴스", "kin": "지식iN"}
SOURCE_LABEL = "네이버 검색 API"
TOTAL_METHOD = "네이버 검색 API의 검색 결과 문서 수(total, 누적) — 검색량 아님"
MONTHLY_METHOD = "네이버 검색 API 날짜순 결과를 작성일 기준으로 달마다 센 문서 수 — 검색량 아님"


def keyword_group(category: Optional[str] = None) -> str:
    """브랜드명 검색어는 'brand', 조합어(브랜드 + 제품군)는 'brand+{제품군}'."""
    return f"brand+{category}" if category else "brand"


def _fact(*, brand_id: str, entity: str, metric: str, value: int, dims: dict, start: date, end: date,
          measured_at: date, label: str, method: str) -> Fact:
    dims = {k: str(v) for k, v in sorted(dims.items())}
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": canonical_decimal(Decimal(value)),
               "unit": "count", "dims": json.dumps(dims, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
               "period": f"{start}~{end}", "measured_at": measured_at.isoformat(), "source": SOURCE_LABEL,
               "method": method}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric,
                value=Decimal(value), unit="count", dims=dims, period_start=start, period_end=end,
                measured_at=measured_at, source=SOURCE_LABEL, method=method, confidence="verified", label=label)


def mention_total_fact(*, brand_id: str, entity: str, channel: str, keyword: str, total: int, measured_at: date,
                       category: Optional[str] = None) -> Fact:
    if channel not in CHANNEL_LABEL:
        raise ValueError(f"channel은 {', '.join(CHANNEL_LABEL)} 중 하나")
    return _fact(brand_id=brand_id, entity=entity, metric="mention_total", value=total,
                 dims={"channel": channel, "keyword_group": keyword_group(category), "keyword": keyword},
                 start=measured_at, end=measured_at, measured_at=measured_at,
                 label=f"'{keyword}' {CHANNEL_LABEL[channel]} 검색 결과 문서 수(누적)", method=TOTAL_METHOD)


def month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def recent_months(today: date, n: int) -> list[str]:
    """오늘이 속한 달은 빼고, 그 앞의 다 끝난 달 n개(오래된 달부터)."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{y:04d}-{m:02d}")
    return out[::-1]


def count_by_month(dates: Iterable[Optional[date]], months: list[str], *,
                   reached_start: bool) -> dict[str, Optional[tuple[int, bool]]]:
    """날짜순(최신 먼저)으로 넘겨 본 문서들의 작성일 → {달: (문서 수, partial) 또는 None}.
    reached_start: 첫 달 1일보다 오래된 글까지 닿았거나 결과가 끝났으면 True. False면(1,000건 한도)
    - 본 글 중 가장 오래된 날짜가 그 달 안이면 그 달은 다 세지 못했으므로 partial
    - 그 달 마지막 날보다도 뒤면 그 달은 하나도 보지 못했으므로 None(0으로 남기지 않는다)."""
    days = [d for d in dates if d is not None]
    counts = {mo: 0 for mo in months}
    for d in days:
        key = f"{d.year:04d}-{d.month:02d}"
        if key in counts:
            counts[key] += 1
    oldest = min(days, default=None)
    out: dict[str, Optional[tuple[int, bool]]] = {}
    for mo in months:
        start, end = month_bounds(mo)
        if reached_start:
            out[mo] = (counts[mo], False)
        elif oldest is None or oldest > end:
            out[mo] = None
        else:
            out[mo] = (counts[mo], start < oldest)
    return out


def mention_monthly_fact(*, brand_id: str, entity: str, channel: str, keyword: str, month: str, count: int,
                         partial: bool, measured_at: date) -> Fact:
    if channel not in CHANNEL_LABEL:
        raise ValueError(f"channel은 {', '.join(CHANNEL_LABEL)} 중 하나")
    start, end = month_bounds(month)
    dims = {"channel": channel, "keyword_group": keyword_group(), "keyword": keyword, "month": month}
    if partial:
        dims["partial"] = "1"
    return _fact(brand_id=brand_id, entity=entity, metric="mention_monthly", value=count, dims=dims, start=start,
                 end=end, measured_at=measured_at,
                 label=f"'{keyword}' {CHANNEL_LABEL[channel]} {month} 문서 수" + (" (일부만 셈)" if partial else ""),
                 method=MONTHLY_METHOD)
