"""Display formatters (PRD 9 표시와 정밀도). The only way numbers become text.

Integers: comma. Share: 1dp %. Rates: 2dp %. Diff: signed 1dp pp. Index: 1dp.
Lead counts >= 10,000: 1dp 만 with trailing zero removed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Callable, Optional, Union

from core.decimalx import quantize

MINUS = "−"  # U+2212, matches reference typography


def _dp(value: Decimal, places: int) -> str:
    return format(quantize(Decimal(value), places), "f")


def fmt_share(value: Decimal) -> str:
    return f"{_dp(value, 1)}%"


def fmt_er(value: Decimal, partial: bool = False) -> str:
    return f"{_dp(value, 2)}%" + ("†" if partial else "")


def fmt_rate(value: Decimal) -> str:
    return f"{_dp(value, 2)}%"


def fmt_times(value: Decimal) -> str:
    """A multiplier, e.g. cocreator_vs_usual (04_지표정의_발견규칙.md 예시: '평소의 0.68배')."""
    return f"{_dp(value, 2)}배"


def fmt_pct_given(value: Decimal) -> str:
    """A percentage someone read off a source: shown with the source's own precision (50.5 -> 50.5%)."""
    return f"{format(Decimal(value).normalize(), 'f')}%"


def fmt_pp(value: Decimal) -> str:
    q = quantize(Decimal(value), 1)
    if q > 0:
        return f"+{format(q, 'f')}pp"
    if q < 0:
        return f"{MINUS}{format(-q, 'f')}pp"
    return "0.0pp"


def fmt_gap(value: Decimal) -> str:
    """Unsigned gap magnitude in pp (e.g. '격차 4.0pp')."""
    return f"{_dp(abs(Decimal(value)), 1)}pp"


def fmt_index(value: Decimal) -> str:
    return _dp(value, 1)


def fmt_int(value: Union[int, Decimal]) -> str:
    return f"{int(value):,}"


def fmt_lead_count(value: Union[int, Decimal]) -> str:
    v = Decimal(value)
    if v < 10000:
        return fmt_int(v)
    text = _dp(v / 10000, 1)
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}만"


def fmt_rank(value: int) -> str:
    return f"{int(value)}위"


def fmt_rank_num(value: int) -> str:
    return str(int(value))


def fmt_months(value: int) -> str:
    return f"{int(value)}개월"


def fmt_days(value: int) -> str:
    return f"{int(value)}일"


def fmt_posts(value: int) -> str:
    return f"{int(value)}건"


def fmt_strength(value: Decimal) -> str:
    return _dp(value, 2)


def fmt_krw(value: Decimal) -> str:
    """Korean money units, as reports write them: 2,987억원 / 58.9조원 / 9,900원."""
    v = Decimal(value)
    for unit, name in ((Decimal(10) ** 12, "조"), (Decimal(10) ** 8, "억")):
        if abs(v) >= unit:
            q = v / unit
            digits = 0 if q == q.to_integral_value() or abs(q) >= 100 else 1
            return f"{fmt_int(quantize(q, digits)) if digits == 0 else f'{quantize(q, digits):,}'}{name}원"
    return f"{fmt_int(quantize(v, 0))}원"


def fmt_count_unit(value: Decimal) -> str:
    return fmt_int(quantize(Decimal(value), 0))


def fmt_date_dot(d: date) -> str:
    return f"{d.year}.{d.month:02d}.{d.day:02d}"


def fmt_month_label(month: str) -> str:
    return f"{int(month.split('-')[1])}월"


def fmt_month_range(start: str, end: str) -> str:
    sy, sm = start.split("-")
    ey, em = end.split("-")
    if sy == ey:
        return f"{sy}.{sm}~{em}"
    return f"{sy}.{sm}~{ey}.{em}"


def fmt_period(start: date, end: date) -> str:
    return f"{fmt_date_dot(start)}~{fmt_date_dot(end)}"


FORMATTERS: dict[str, Callable] = {
    "share": fmt_share,
    "rate": fmt_rate,
    "pct_given": fmt_pct_given,
    "pp": fmt_pp,
    "gap": fmt_gap,
    "index": fmt_index,
    "int": fmt_int,
    "lead_count": fmt_lead_count,
    "rank": fmt_rank,
    "rank_num": fmt_rank_num,
    "months": fmt_months,
    "posts": fmt_posts,
    "strength": fmt_strength,
    "krw": fmt_krw,
    "count": fmt_count_unit,
    "times": fmt_times,
    "days": fmt_days,
}


def format_value(formatter: str, value, partial: bool = False) -> Optional[str]:
    if value is None:
        return None
    if formatter == "er":
        return fmt_er(value, partial)
    if formatter not in FORMATTERS:
        raise KeyError(f"unknown formatter {formatter}")
    return FORMATTERS[formatter](value)


# Default formatter by derived unit, used when a manual fact is inserted into text.
UNIT_FORMATTER = {"percent": "pct_given", "pp": "pp", "count": "int", "rank": "rank", "months": "months",
                  "index": "index", "krw": "krw"}
