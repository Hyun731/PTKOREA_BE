"""P2-1 검색 점유 세트: 키 타겟 필터, 조합어 검색어, 카테고리 dims (core/ingestion/search_index.py)."""
from datetime import date
from decimal import Decimal

from core.ingestion.search_index import combo_keywords, naver_target_filter, window_sum_fact


def test_target_filter_covers_every_overlapping_age_band():
    assert naver_target_filter(25, 34, "all") == {"ages": ["4", "5"]}
    assert naver_target_filter(19, 24, "female") == {"ages": ["3"], "gender": "f"}
    assert naver_target_filter(27, 31, "all") == {"ages": ["4", "5"]}  # 범위가 걸치는 연령대 모두
    assert naver_target_filter(35, None, "male") == {"ages": ["6", "7", "8", "9", "10", "11"], "gender": "m"}


def test_target_filter_none_when_it_narrows_nothing():
    assert naver_target_filter(None, None, "all") is None
    assert naver_target_filter(0, 120, "all") is None  # 모든 연령대 = 전체와 같음
    assert naver_target_filter(None, None, "female") == {"gender": "f"}


def test_combo_keywords_with_and_without_space_deduped_and_capped():
    assert combo_keywords(["샘소나이트", "Samsonite"], "캐리어") == \
        ["샘소나이트 캐리어", "샘소나이트캐리어", "Samsonite 캐리어", "Samsonite캐리어"]
    assert len(combo_keywords([f"이름{i}" for i in range(15)], "가방")) == 20


def test_category_dims_only_on_combo_sums_and_name_ids_unchanged():
    kw = dict(brand_id="B1", entity="브랜드A", window_label="12M", total=Decimal("120.5"), seg="all", scale_id="s",
              period_start=date(2025, 10, 1), period_end=date(2026, 9, 30), measured_at=date(2026, 10, 1))
    name, combo = window_sum_fact(**kw), window_sum_fact(**kw, cat="가방")
    assert "cat" not in name.dims and combo.dims["cat"] == "가방" and name.id != combo.id
    assert window_sum_fact(**kw, cat=None).id == name.id  # 카테고리 없는 Fact는 예전과 같은 id
