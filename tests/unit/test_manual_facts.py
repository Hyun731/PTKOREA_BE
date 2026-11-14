from datetime import date
from decimal import Decimal

import pytest

from core.ingestion.manual import make_manual_fact
from core.composition.formatters import UNIT_FORMATTER, format_value


def _fact(metric: str, value: str):
    return make_manual_fact(
        brand_id="B1", entity="Brand Alpha", metric=metric, value=value,
        measured_at=date(2026, 11, 15), source="Synthetic source",
    )


def test_manual_facts_preserve_extended_units():
    expected = {
        "amount_usd": "usd",
        "percentage_point": "pp",
        "score": "score",
        "ratio": "ratio",
        "duration_days": "days",
        "duration_months": "months",
        "duration_years": "years",
        "group_count": "group",
    }
    for metric, unit in expected.items():
        fact = _fact(metric, "2")
        assert fact.unit == unit
        assert format_value(UNIT_FORMATTER[unit], fact.value)


def test_directional_manual_facts_allow_negative_values():
    assert _fact("percent", "-12.5").value == Decimal("-12.5")
    assert _fact("percentage_point", "-3.2").value == Decimal("-3.2")
    assert _fact("score", "-7").value == Decimal("-7")


def test_non_negative_manual_units_still_reject_negative_values():
    with pytest.raises(ValueError, match="음수 값"):
        _fact("duration_days", "-1")
