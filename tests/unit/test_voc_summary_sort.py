"""5-1 VOC summary must not crash when some quotes have no date (date vs id comparison)."""
from datetime import date
from types import SimpleNamespace

from core.composition.customer import _newest_first


def _m(id_, published=None, activity=None):
    return SimpleNamespace(id=id_, activity_date=activity, source=SimpleNamespace(published_at=published))


def test_undated_quotes_sort_after_dated_ones_without_error():
    rows = [_m("EV-b"), _m("EV-a", published=date(2026, 3, 1)), _m("EV-c", activity=date(2026, 5, 1))]
    ordered = sorted(rows, key=_newest_first, reverse=True)
    assert [m.id for m in ordered] == ["EV-c", "EV-a", "EV-b"]
