"""Decimal helpers shared by ingestion, metrics and formatters.

PRD 8/9: parse with Decimal, reject NaN/Infinity, keep raw precision, no intermediate
rounding. Serialization quantizes to 10 decimals (values) / 6 decimals (strength) with
ROUND_HALF_UP.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

VALUE_PLACES = 10
STRENGTH_PLACES = 6


class DecimalParseError(ValueError):
    pass


def parse_decimal(raw: str | int | Decimal | None) -> Decimal | None:
    """Parse a CSV/JSON value. Empty string and None mean null (not zero)."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int) and not isinstance(raw, bool):
        value = Decimal(raw)
    else:
        text = str(raw).strip()
        if text == "":
            return None
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise DecimalParseError(f"숫자가 아닙니다: {text!r}") from exc
    if not value.is_finite():
        raise DecimalParseError("NaN·Infinity는 허용되지 않습니다")
    return value


def parse_count(raw: str | int | None) -> int | None:
    """Non-negative integer count or null."""
    value = parse_decimal(raw)
    if value is None:
        return None
    if value < 0:
        raise DecimalParseError("음수 카운트는 허용되지 않습니다")
    if value != value.to_integral_value():
        raise DecimalParseError("정수가 아닙니다")
    return int(value)


def quantize(value: Decimal, places: int) -> Decimal:
    exp = Decimal(1).scaleb(-places)
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(exp, rounding=ROUND_HALF_UP)


def q10(value: Decimal) -> Decimal:
    return quantize(value, VALUE_PLACES)


def q_strength(value: Decimal) -> Decimal:
    return quantize(value, STRENGTH_PLACES)


def ser(value: Decimal | None) -> str | None:
    """Serialize a derived value as a 10-decimal string."""
    return None if value is None else format(q10(value), "f")


def ser_strength(value: Decimal) -> str:
    return format(q_strength(value), "f")


def clamp01(value: Decimal) -> Decimal:
    if value < 0:
        return Decimal(0)
    if value > 1:
        return Decimal(1)
    return value


def canonical_decimal(value: Decimal | None) -> str | None:
    """Normalized string used in content hashes: '100.0000000000' and '100' hash equal."""
    if value is None:
        return None
    normalized = value.normalize()
    text = format(normalized, "f")
    return text
