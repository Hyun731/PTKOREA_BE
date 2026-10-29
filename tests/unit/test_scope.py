"""Research scope (팩트북 표준 목차 §3): catalog order, defaults, overrides and direction sentences."""
from datetime import date

import pytest

from app.services import scope
from core.schemas.project import Project


def project(**kw) -> Project:
    data = {
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "샘소나이트", "competitors": ["리모와", "투미"], "benchmarks": ["젠틀몬스터"],
                    "categories": ["러기지"]}],
        "enabled_slides": ["cover", "3-1", "C1", "C2", "M1"],
    }
    data.update(kw)
    return Project.model_validate(data)


def by_id(p: Project) -> dict:
    return {r["item_id"]: r for r in scope.resolve(p)}


def test_catalog_runs_company_competitor_customer():
    parts = [s["part"] for s in scope.ITEMS]
    assert parts == sorted(parts, key=["company", "competitor", "customer"].index)
    assert len(scope.ITEMS) >= 25


def test_defaults_follow_enabled_slides_and_guide_periods():
    r = by_id(project())
    assert r["2-7"]["enabled"] and r["2-8"]["enabled"] and r["3-7"]["enabled"] and r["3-1"]["enabled"]
    assert not r["2-6"]["enabled"] and not r["3-2"]["enabled"]  # their slides are off
    assert not r["4-1"]["enabled"]  # items without a collector start off
    assert (r["4-1"]["start"], r["4-1"]["end"]) == (date(2026, 4, 1), date(2026, 9, 30))  # 최근 6개월
    assert r["2-8"]["automation"] == "auto" and r["2-1"]["automation"] == "manual"


def test_direction_reads_like_a_plan():
    p = project(scope=[{"item_id": "3-7", "targets": ["투미"], "period": "months", "months": 24, "max_items": 4,
                        "focus": "팝업·오프라인 행사를 먼저 봅니다."}])
    r = by_id(p)["3-7"]
    lines = scope.direction(scope.BY_ID["3-7"], r, p)
    assert lines[0] == "경쟁사 투미 캠페인·활동 사례를 조사합니다."
    assert lines[1] == "최근 24개월(2024.10.01 ~ 2026.09.30) 안의 것만 봅니다."
    assert "자동으로 찾습니다" in lines[2] and "최대 4개" in lines[3]
    assert lines[-1] == "팝업·오프라인 행사를 먼저 봅니다."
    manual = scope.direction(scope.BY_ID["4-2"], by_id(p)["4-2"], p)
    assert manual[0].startswith("샘소나이트 사기") and "직접 넣습니다" in manual[2]


def test_legacy_window_becomes_custom_period():
    p = project(section_windows=[{"section_id": "influencer", "label": "3M", "start": "2026-07-01", "end": "2026-09-30"}])
    r = by_id(p)["2-7"]
    assert r["period"] == "custom" and r["start"] == date(2026, 7, 1)


def test_unknown_item_and_channel_are_rejected():
    with pytest.raises(ValueError):
        scope.validate(project(scope=[{"item_id": "9-9"}]))
    with pytest.raises(ValueError):
        scope.validate(project(scope=[{"item_id": "4-1", "channels": ["instagram_owned"]}]))
    with pytest.raises(ValueError):
        project(scope=[{"item_id": "4-1", "period": "custom", "start": "2026-05-01"}])


def test_requested_keywords_lead_the_search_queries():
    from datetime import date as d
    from types import SimpleNamespace as NS

    from app.services.research import build_queries
    p = project(scope=[{"item_id": "3-7", "keywords": ["팝업스토어"], "focus": "팝업을 먼저 봅니다."}])
    item = NS(brand_id="B1", entity="투미", role="competitor", section_id="campaign", scope_id="3-7",
              period_start=d(2026, 1, 1), period_end=d(2026, 9, 30))
    queries = build_queries(item, NS(config=p.model_dump(mode="json")))
    assert queries[0] == "투미 팝업스토어 2026" and "투미 캠페인 2026" in queries
