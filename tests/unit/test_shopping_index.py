"""P2-2 쇼핑인사이트 Fact (core/ingestion/shopping_index.py)."""
from datetime import date
from decimal import Decimal

from core.ingestion.shopping_index import click_index_facts, peak_facts, pick_top_category, share_facts

DAY = date(2026, 10, 1)


def _series(kw, ratios):
    return {"group": kw, "points": [{"period": f"2026-{m:02d}-01", "ratio": r} for m, r in enumerate(ratios, start=1)]}


def test_pick_top_category_by_months_with_data():
    picked = pick_top_category({"50000001": {"캐리어": 12, "립스틱": 6}, "50000002": {"캐리어": 0, "립스틱": 12},
                                "50000008": {"캐리어": 12}}, ["캐리어", "립스틱", "기저귀"])
    assert picked == {"캐리어": "50000001", "립스틱": "50000002", "기저귀": None}  # 동점이면 앞선 코드


def test_click_index_facts_per_keyword_month_with_scale():
    facts = click_index_facts(brand_id="B1", category_code="50000001", results=[_series("캐리어", [10, 20.04])],
                              scale_id="s1", measured_at=DAY)
    assert [(f.dims["month"], f.value) for f in facts] == [("2026-01", Decimal("10.0")), ("2026-02", Decimal("20.0"))]
    assert facts[0].unit == "index" and facts[0].dims["scale_id"] == "s1" and facts[0].period_end == date(2026, 1, 31)


def test_peaks_are_months_well_above_the_average():
    ratios = [40, 40, 40, 40, 40, 40, 100, 90, 40, 40, 40, 40]  # 평균 49.17
    idx = click_index_facts(brand_id="B1", category_code="c", results=[_series("캐리어", ratios)], scale_id="s",
                            measured_at=DAY)
    peaks = peak_facts(idx, lift=Decimal("1.2"), measured_at=DAY)
    assert [(f.dims["month"], f.value) for f in peaks] == [("2026-07", Decimal("203.4")), ("2026-08", Decimal("183.1"))]
    assert peaks[0].unit == "percent" and peaks[0].dims["n_months"] == "12"
    short = click_index_facts(brand_id="B1", category_code="c", results=[_series("백팩", [10, 90, 10])], scale_id="s",
                              measured_at=DAY)
    assert peak_facts(short, lift=Decimal("1.2"), measured_at=DAY) == []  # 6개월 미만은 성수기를 말하지 않음


def test_shares_average_the_period_and_sum_to_100():
    res = [{"group": "c", "points": [{"period": "2026-01-01", "ratio": 30, "group": "f"},
                                      {"period": "2026-01-01", "ratio": 10, "group": "m"},
                                      {"period": "2026-02-01", "ratio": 50, "group": "f"},
                                      {"period": "2026-02-01", "ratio": 10, "group": "m"}]}]
    facts = share_facts(brand_id="B1", keyword="캐리어", category_code="c", by="gender", results=res,
                        start=date(2026, 1, 1), end=date(2026, 2, 28), measured_at=DAY)
    assert {f.dims["group"]: f.value for f in facts} == {"f": Decimal("80.0"), "m": Decimal("20.0")}
    assert facts[0].label == "캐리어 쇼핑 클릭 여성 비중"
    assert share_facts(brand_id="B1", keyword="k", category_code="c", by="age", results=[], start=DAY, end=DAY,
                       measured_at=DAY) == []


def test_same_input_same_ids():
    a = click_index_facts(brand_id="B1", category_code="c", results=[_series("캐리어", [1, 2])], scale_id="s", measured_at=DAY)
    b = click_index_facts(brand_id="B1", category_code="c", results=[_series("캐리어", [1, 2])], scale_id="s", measured_at=DAY)
    assert [f.id for f in a] == [f.id for f in b]
