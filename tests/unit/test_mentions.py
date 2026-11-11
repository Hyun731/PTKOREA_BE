"""P2-4 언급량 Fact (core/ingestion/mentions.py)."""
from datetime import date

import pytest

from core.ingestion.mentions import (
    count_by_month, keyword_group, mention_monthly_fact, mention_total_fact, recent_months,
)

TODAY = date(2026, 11, 11)


def test_total_fact_is_labelled_as_document_count_not_search_volume():
    f = mention_total_fact(brand_id="SO", entity="샘소나이트", channel="blog", keyword="샘소나이트", total=21989,
                           measured_at=TODAY)
    assert f.metric == "mention_total" and f.value == 21989 and f.unit == "count"
    assert f.dims == {"channel": "blog", "keyword_group": "brand", "keyword": "샘소나이트"}
    assert f.period_start == f.period_end == TODAY and f.verification_status == "candidate"
    assert "문서 수(누적)" in f.label and "검색량" not in f.label and "검색량 아님" in f.method


def test_combo_keyword_group_and_stable_id():
    a = mention_total_fact(brand_id="SO", entity="샘소나이트", channel="news", keyword="샘소나이트 캐리어", total=34,
                           measured_at=TODAY, category="캐리어")
    b = mention_total_fact(brand_id="SO", entity="샘소나이트", channel="news", keyword="샘소나이트 캐리어", total=34,
                           measured_at=TODAY, category="캐리어")
    assert a.dims["keyword_group"] == "brand+캐리어" == keyword_group("캐리어") and a.id == b.id
    other = mention_total_fact(brand_id="SO", entity="샘소나이트", channel="news", keyword="샘소나이트 캐리어", total=35,
                               measured_at=TODAY, category="캐리어")
    assert other.id != a.id
    with pytest.raises(ValueError):
        mention_total_fact(brand_id="SO", entity="x", channel="cafearticle", keyword="x", total=1, measured_at=TODAY)


def test_recent_months_are_the_last_complete_months():
    assert recent_months(TODAY, 3) == ["2026-08", "2026-09", "2026-10"]
    assert recent_months(date(2026, 2, 3), 3) == ["2025-11", "2025-12", "2026-01"]


def test_count_by_month_marks_months_the_cap_did_not_reach_as_partial():
    months = ["2026-08", "2026-09", "2026-10"]
    dates = [date(2026, 10, 30), date(2026, 10, 2), date(2026, 9, 20), date(2026, 11, 1), None]
    # 한도에 걸려 9월 20일까지만 봤다 → 9월은 일부, 8월은 하나도 못 셈(0이지만 일부)
    out = count_by_month(dates, months, reached_start=False)
    assert out == {"2026-08": (0, True), "2026-09": (1, True), "2026-10": (2, False)}
    # 첫 달 이전까지 닿았으면 0도 실제 관측
    assert count_by_month(dates, months, reached_start=True)["2026-08"] == (0, False)


def test_monthly_fact_carries_partial_only_when_capped():
    f = mention_monthly_fact(brand_id="SO", entity="샘소나이트", channel="blog", keyword="샘소나이트", month="2026-09",
                             count=812, partial=True, measured_at=TODAY)
    assert f.metric == "mention_monthly" and f.dims["partial"] == "1" and f.dims["month"] == "2026-09"
    assert (f.period_start, f.period_end) == (date(2026, 9, 1), date(2026, 9, 30)) and "일부" in f.label
    full = mention_monthly_fact(brand_id="SO", entity="샘소나이트", channel="blog", keyword="샘소나이트", month="2026-09",
                                count=812, partial=False, measured_at=TODAY)
    assert "partial" not in full.dims and full.id != f.id


def test_qc_blocks_calling_document_counts_search_volume_but_not_the_index_disclaimer():
    from core.quality.qc import OVERCLAIMS

    assert {"블로그 검색량", "검색량이 많", "검색량 1위"} <= set(OVERCLAIMS)
    # 검색 지수 장표의 각주("절대 검색량 아님")는 걸리지 않는다
    for footnote in ("상대 지수 0~100 · 절대 검색량 아님", "검색어 그룹 상대 지수 합 기준(절대 검색량 아님)",
                     "블로그 검색 결과 문서 수(누적)"):
        assert not [p for p in OVERCLAIMS if p in footnote]
