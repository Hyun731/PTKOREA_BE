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


def test_everything_is_in_by_default_and_slides_follow_items():
    p = project()
    r = by_id(p)
    # 3-10(업종 KPI)·2-9(커머스 리뷰)는 업종에 따라서만 기본으로 켜진다 — 이 프로젝트는 업종 미설정.
    industry_gated = {"3-10", "2-9"}
    assert all(x["enabled"] for iid, x in r.items() if iid not in industry_gated)
    assert not r["3-10"]["enabled"] and not r["2-9"]["enabled"]
    assert {"2-1", "2-4", "2-8a", "3-1", "C1", "M1", "cover", "A-source"} <= set(scope.slides(p))
    off = project(scope=[{"item_id": "2-6", "enabled": False}, {"item_id": "2-8", "enabled": False}])
    left = set(scope.slides(off))
    assert "2-1" not in left and "1-6" not in left and "C1" in left  # 3-7 still brings the case cards
    assert (r["4-1"]["start"], r["4-1"]["end"]) == (date(2026, 4, 1), date(2026, 9, 30))  # 최근 6개월
    assert r["2-8"]["automation"] == "auto" and r["2-1"]["automation"] == "manual"


def test_industry_kpi_item_defaults_on_only_for_metric_industries():
    review = project(brands=[{"id": "B1", "name": "샘소나이트", "competitors": ["리모와"], "categories": ["러기지"],
                              "industry": "패션"}])
    assert by_id(review)["3-10"]["enabled"] is False  # 리뷰 중심 업종
    metric = project(brands=[{"id": "B1", "name": "은행A", "competitors": ["은행B"], "categories": ["금융"],
                              "industry": "금융"}])
    assert by_id(metric)["3-10"]["enabled"] is True  # 지표 중심 업종
    assert "M2" in scope.slides(metric)


def test_commerce_review_item_defaults_on_only_for_review_industries():
    review = project(brands=[{"id": "B1", "name": "샘소나이트", "competitors": ["리모와"], "categories": ["러기지"],
                              "industry": "패션"}])
    assert by_id(review)["2-9"]["enabled"] is True  # 리뷰 중심 업종(전자·뷰티·패션은 필수)
    assert "CM1" in scope.slides(review)
    metric = project(brands=[{"id": "B1", "name": "은행A", "competitors": ["은행B"], "categories": ["금융"],
                              "industry": "금융"}])
    assert by_id(metric)["2-9"]["enabled"] is False  # 지표 중심 업종
    assert "CM1" not in scope.slides(metric)


def test_direction_reads_like_a_plan():
    p = project(scope=[{"item_id": "3-7", "targets": ["투미"], "period": "months", "months": 24, "max_items": 4,
                        "focus": "팝업·오프라인 행사를 먼저 봅니다."}])
    r = by_id(p)["3-7"]
    lines = scope.direction(scope.BY_ID["3-7"], r, p)
    assert lines[0] == "경쟁사 투미 캠페인·활동 사례를 조사합니다."
    assert lines[1] == "최근 24개월(2024.10.01 ~ 2026.09.30) 안의 것만 봅니다."
    assert "자동으로 찾습니다" in lines[2] and "최대 4개" in lines[3]
    assert lines[-1] == "팝업·오프라인 행사를 먼저 봅니다."
    manual = scope.direction(scope.BY_ID["2-4"], by_id(p)["2-4"], p)
    assert manual[0].startswith("샘소나이트 인지") and "직접 넣습니다" in manual[2]
    issue = scope.direction(scope.BY_ID["4-2"], by_id(p)["4-2"], p)  # P4-3: 웹 기사와 네이버 뉴스로 자동
    assert issue[0].startswith("샘소나이트 사기") and "네이버 뉴스에서 자동으로 찾습니다" in issue[2]


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


def test_market_queries_append_industry_keyword_hints_when_available():
    """피드백 #1(업종별 variation): 프로필 있는 업종은 시장 조사 질의에 서브트렌드 키워드가 덧붙는다."""
    from datetime import date as d
    from types import SimpleNamespace as NS

    from app.services.research import build_queries
    item = NS(brand_id="B1", entity="샘소나이트", role="self", section_id="market", scope_id="3-1",
             period_start=d(2026, 1, 1), period_end=d(2026, 9, 30))

    travel = project(brands=[{"id": "B1", "name": "샘소나이트", "competitors": ["리모와"], "categories": ["러기지"],
                             "industry": "여행"}])
    queries = build_queries(item, NS(config=travel.model_dump(mode="json")))
    assert any("트래블룩" in q for q in queries)

    none_yet = project(brands=[{"id": "B1", "name": "샘소나이트", "competitors": ["리모와"], "categories": ["러기지"],
                                "industry": "금융"}])
    queries2 = build_queries(item, NS(config=none_yet.model_dump(mode="json")))
    assert not any("트래블룩" in q for q in queries2)  # 프로필도 확정 후보도 없으면 덧붙지 않는다


def test_regulation_item_builds_policy_specific_queries_not_market_size_ones():
    """피드백 #1 축 4(3-4 규제와 정책): 3-1과 같은 collector("market")지만 질의는 정책 전용."""
    from datetime import date as d
    from types import SimpleNamespace as NS

    from app.services.research import build_queries
    p = NS(config=project().model_dump(mode="json"))
    policy_item = NS(brand_id="B1", entity="러기지", role="market", section_id="market", scope_id="3-4",
                     period_start=d(2026, 1, 1), period_end=d(2026, 9, 30))
    queries = build_queries(policy_item, p)
    assert any("정책" in q for q in queries) and not any("시장 규모" in q for q in queries)

    market_item = NS(**{**policy_item.__dict__, "scope_id": "3-1"})
    market_queries = build_queries(market_item, p)
    assert any("시장 규모" in q for q in market_queries) and not any("정책" in q for q in market_queries)


def test_upload_line_only_when_an_upload_channel_is_chosen():
    p = project()
    assert not any("내부 자료" in x for x in scope.direction(scope.BY_ID["2-7"], by_id(p)["2-7"], p))
    assert any("내부 자료" in x for x in scope.direction(scope.BY_ID["2-4"], by_id(p)["2-4"], p))


def test_owned_channel_item_covers_self_and_competitors_but_only_self_is_required():
    p = project()
    rows = [r for r in scope.generate_items(p) if r["scope_id"] == "2-6"]
    assert {(r["entity"], r["role"], r["required"]) for r in rows} == {
        ("샘소나이트", "self", True), ("리모와", "competitor", False), ("투미", "competitor", False)}


def test_owned_channel_targets_narrow_which_competitors_but_never_drop_self():
    p = project(scope=[{"item_id": "2-6", "targets": ["리모와"]}])
    rows = [r for r in scope.generate_items(p) if r["scope_id"] == "2-6"]
    assert {r["entity"] for r in rows} == {"샘소나이트", "리모와"}


def test_positioning_runs_web_issue_and_ad_library_as_separate_items():
    rows = [r for r in scope.generate_items(project()) if r["scope_id"] == "3-5"]
    assert {(r["entity"], r["section_id"]) for r in rows} == {
        ("리모와", "issue"), ("리모와", "ad_library"),
        ("투미", "issue"), ("투미", "ad_library"),
    }
    assert {tuple(r["channels"]) for r in rows} == {("web",), ("ad_library",)}


def test_voc_items_default_to_their_own_months_period_not_a_broken_custom_window():
    """5-1's 24-month default is wider than a typical project period — resolving it twice (as a
    real save does, once section_windows is recomputed) must not turn it into an invalid 'custom'
    ScopeSetting with no start/end (regression: _default_setting()'s legacy-window heuristic)."""
    p = project()  # period.start..end is a single 9-month window
    core = Project.model_validate({**p.model_dump(mode="json"), "section_windows": scope.section_windows(p)})
    r = by_id(core)["5-1"]
    assert r["period"] == "months" and r["months"] == 24
    assert core.scope == []  # nothing was silently written as an override either
