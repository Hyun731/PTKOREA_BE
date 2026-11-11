"""쇼핑인사이트(네이버 데이터랩) 응답 → Fact (P2-2 품목별 수요·성수기).

값은 모두 응답 안 상대 비율이다(가장 큰 값 = 100). 절대 클릭 수가 아니므로 장표에는 '클릭 지수'·'비중'으로만
쓴다. 같은 요청에서 나온 값끼리만 비교할 수 있어 scale_id를 dims에 남긴다.

- shop_click_index: 분야 안 키워드(제품군)의 월별 클릭 지수 — 한 요청에 제품군 최대 5개를 같은 스케일로
- shop_click_share: 그 키워드를 누른 연령대·성별 비중(%) — 기간 전체 평균
- shop_peak_lift: 성수기 달 — 그 달 지수 ÷ 12개월 평균 × 100(%), 기준(peak_lift)을 넘는 달만
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact

SOURCE_LABEL = "네이버 데이터랩 쇼핑인사이트"
AGE_LABEL = {"10": "10대", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대 이상"}
GENDER_LABEL = {"f": "여성", "m": "남성"}


def _fact(*, brand_id: str, entity: str, metric: str, value: Decimal, unit: str, dims: dict, start: date, end: date,
          measured_at: date, label: str) -> Fact:
    dims = {k: str(v) for k, v in sorted(dims.items())}
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": str(value), "unit": unit,
               "dims": json.dumps(dims, ensure_ascii=False, sort_keys=True), "period": f"{start}~{end}",
               "measured_at": measured_at.isoformat(), "source": SOURCE_LABEL}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric, value=value,
                unit=unit, dims=dims, period_start=start, period_end=end, measured_at=measured_at, source=SOURCE_LABEL,
                confidence="verified", label=label)


def _q(x: float, places: str = "0.1") -> Decimal:
    return Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def pick_top_category(points_by_code: dict[str, dict[str, int]], keywords: list[str]) -> dict[str, Optional[str]]:
    """제품군 검색어마다 데이터가 가장 많은 최상위 분야. points_by_code: {분야코드: {검색어: 월별 점 수}}.
    점 수가 같으면 코드 순서가 앞선 쪽, 어디에도 데이터가 없으면 None."""
    out: dict[str, Optional[str]] = {}
    for kw in keywords:
        best = max(sorted(points_by_code), key=lambda c: points_by_code[c].get(kw, 0), default=None)
        out[kw] = best if best and points_by_code[best].get(kw, 0) > 0 else None
    return out


def click_index_facts(*, brand_id: str, category_code: str, results: list[dict], scale_id: str,
                      measured_at: date) -> list[Fact]:
    """shopping_keyword_trend 응답(키워드 계열들) → 키워드 × 월 지수 Fact."""
    out = []
    for r in results:
        kw = r["group"]
        for pt in r["points"]:
            month = pt["period"][:7]
            start, end = _month_bounds(month)
            out.append(_fact(brand_id=brand_id, entity=kw, metric="shop_click_index", value=_q(pt["ratio"]), unit="index",
                             dims={"month": month, "category": category_code, "scale_id": scale_id}, start=start, end=end,
                             measured_at=measured_at, label=f"{kw} 쇼핑 클릭 지수 {month}"))
    return out


def peak_facts(index_facts: Iterable[Fact], *, lift: Decimal, measured_at: date) -> list[Fact]:
    """키워드마다 월 지수가 기간 평균의 lift배 이상인 달 → shop_peak_lift(%) Fact."""
    by_kw: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for f in index_facts:
        if f.metric == "shop_click_index":
            by_kw[(f.brand_id, f.entity)].append(f)
    out = []
    for (brand_id, kw), fs in sorted(by_kw.items()):
        if len(fs) < 6:  # 반년도 안 되는 계열로 성수기를 말하지 않는다
            continue
        mean = sum(f.value for f in fs) / len(fs)
        if mean <= 0:
            continue
        for f in sorted(fs, key=lambda f: f.dims["month"]):
            ratio = f.value / mean
            if ratio >= lift:
                out.append(_fact(brand_id=brand_id, entity=kw, metric="shop_peak_lift", value=_q(float(ratio * 100)),
                                 unit="percent", dims={"month": f.dims["month"], "category": f.dims["category"],
                                                       "n_months": len(fs)},
                                 start=f.period_start, end=f.period_end, measured_at=measured_at,
                                 label=f"{kw} 성수기 {f.dims['month']} (평균 대비)"))
    return out


def share_facts(*, brand_id: str, keyword: str, category_code: str, by: str, results: list[dict], start: date,
                end: date, measured_at: date) -> list[Fact]:
    """shopping_keyword_breakdown 응답 → 연령대·성별 비중(%) — 기간 전체 평균을 합 100으로."""
    sums: dict[str, float] = defaultdict(float)
    for r in results:
        for pt in r["points"]:
            if pt.get("group"):
                sums[pt["group"]] += pt["ratio"]
    total = sum(sums.values())
    if total <= 0:
        return []
    labels = AGE_LABEL if by == "age" else GENDER_LABEL
    metric = "shop_click_share"
    return [_fact(brand_id=brand_id, entity=keyword, metric=metric, value=_q(v * 100 / total), unit="percent",
                  dims={"by": by, "group": g, "category": category_code}, start=start, end=end, measured_at=measured_at,
                  label=f"{keyword} 쇼핑 클릭 {labels.get(g, g)} 비중")
            for g, v in sorted(sums.items())]
