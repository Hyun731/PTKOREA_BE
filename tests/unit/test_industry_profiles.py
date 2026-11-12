"""P4-2 업종 프로필 12개: 형식 검사, 업종이 다르면 조사 항목·질의가 달라지는지, 초안 도구."""
import string
from datetime import date
from types import SimpleNamespace as NS

from app.services import industry_keywords, scope
from app.services.research import build_queries
from core.industry_profiles import AXES, INDUSTRY_PROFILES, axis_queries
from core.schemas.project import INDUSTRIES, Project
from integrations.base import CallResult
from integrations.naver.client import SHOP_TOP_CATEGORIES
from tools import draft_industry_profiles as draft_tool


def _project(industry: str, category: str = "러기지") -> Project:
    return Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드", "competitors": ["경쟁사"], "categories": [category], "industry": industry}],
        "enabled_slides": ["cover"],
    })


def _item(scope_id: str, section_id: str = "market", entity: str = "러기지", role: str = "market"):
    return NS(brand_id="B1", entity=entity, role=role, section_id=section_id, scope_id=scope_id,
              period_start=date(2026, 1, 1), period_end=date(2026, 9, 30))


def _queries(industry: str, scope_id: str, **kw) -> list[str]:
    return build_queries(_item(scope_id, **kw), NS(config=_project(industry).model_dump(mode="json")))


def test_every_industry_has_a_well_formed_profile():
    assert set(INDUSTRY_PROFILES) == set(INDUSTRIES)
    gated = set(draft_tool.GATED_SCOPE_ITEMS)
    for name, p in INDUSTRY_PROFILES.items():
        assert set(p.axis_queries) <= set(AXES), name
        for templates in p.axis_queries.values():
            for t in templates:
                fields = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
                assert fields <= {"category", "year"} and "category" in fields, (name, t)
        assert set(p.shopping_categories.values()) <= set(SHOP_TOP_CATEGORIES), name
        assert set(p.default_scope_on) <= gated and set(p.default_scope_on) <= set(scope.BY_ID), name


def test_axis_queries_fill_category_and_year():
    assert axis_queries("여행", "policy", category="러기지", year=2026)[0] == "러기지 면세 한도 2026"
    assert axis_queries(None, "policy", category="러기지", year=2026) == []


def test_travel_and_beauty_build_different_queries():
    travel, beauty = _queries("여행", "3-1"), _queries("뷰티", "3-1")
    assert travel != beauty
    assert "러기지 해외여행 수요 2026" in travel and "러기지 인기 성분 2026" in beauty
    # 업종 특화 질의는 실행 한도(MAX_QUERIES_PER_ITEM) 안에 들어간다.
    from app.services.research import MAX_QUERIES_PER_ITEM
    assert "러기지 해외여행 수요 2026" in travel[:MAX_QUERIES_PER_ITEM]
    assert _queries("여행", "3-4") != _queries("뷰티", "3-4")
    assert any("면세 한도" in q for q in _queries("여행", "3-4"))
    kpi = _queries("여행", "3-10", section_id="market_kpi", entity="브랜드", role="self")
    assert kpi[0] == "브랜드 출입국자 수 2026"


def test_travel_and_beauty_plan_different_items():
    travel = {(i["scope_id"], i["entity"]) for i in scope.generate_items(_project("여행"))}
    beauty = {(i["scope_id"], i["entity"]) for i in scope.generate_items(_project("뷰티"))}
    assert travel != beauty
    assert any(s == "3-10" for s, _ in travel)  # 여행: 출입국자 수 같은 업종 KPI를 기본으로 본다
    assert not any(s == "3-10" for s, _ in beauty)


def test_planner_can_still_turn_a_profile_default_off():
    p = Project.model_validate({**_project("여행").model_dump(mode="json"),
                                "scope": [{"item_id": "3-10", "enabled": False}]})
    assert not next(r for r in scope.resolve(p) if r["item_id"] == "3-10")["enabled"]


def test_unreviewed_draft_hints_become_candidates_without_paid_calls():
    calls = []
    industry_keywords.SEARCH[:] = [lambda *a, **k: calls.append(a)]
    try:
        assert industry_keywords.missing({"industry": "뷰티"}) is True
        found = industry_keywords.discover("뷰티", ledger=None)
    finally:
        industry_keywords.SEARCH.clear()
    assert found and all(h["status"] == "candidate" for h in found)
    assert not calls


def test_draft_tool_normalizes_model_output():
    raw = {
        "keyword_hints": ["  트래블룩 ", "트래블룩", "고프코어"], "gov_stats": ["한국관광공사 출입국 통계"],
        "axis_queries": {"market": ["{category} 여행 시장 {year}", "{brand} 잘못된 틀"], "demand": [], "consumer": [],
                         "policy": ["{category} 면세 한도 {year}"]},
        "key_metrics": ["출입국자 수"], "season_calendar": ["07-08 여름 휴가"], "policy_keywords": ["면세 한도"],
        "shopping_categories": [{"product_group": "캐리어", "code": "50000001"}, {"product_group": "엉터리", "code": "1"}],
        "default_scope_on": ["3-10", "2-6"],
    }
    p = draft_tool.normalize(raw)
    assert p["keyword_hints"] == ("트래블룩", "고프코어")
    assert p["axis_queries"] == {"market": ("{category} 여행 시장 {year}",), "policy": ("{category} 면세 한도 {year}",)}
    assert p["shopping_categories"] == {"캐리어": "50000001"}
    assert p["default_scope_on"] == ("3-10",)


def test_draft_tool_searches_then_structures():
    seen = {}
    draft_tool.SEARCH[:] = [lambda qs, **k: CallResult(data={"results": [
        {"url": "https://example.kr/a", "title": "여행 통계", "snippet": "출입국자 수 증가"}]})]

    def fake(system, user, schema, **k):
        seen["user"] = user
        return CallResult(data={"keyword_hints": ["트래블룩"], "gov_stats": [], "axis_queries": {a: [] for a in AXES},
                                "key_metrics": [], "season_calendar": [], "policy_keywords": [],
                                "shopping_categories": [], "default_scope_on": []})
    draft_tool.STRUCTURED[:] = [fake]
    try:
        out = draft_tool.draft("여행")
    finally:
        draft_tool.SEARCH.clear()
        draft_tool.STRUCTURED.clear()
    assert out["profile"]["keyword_hints"] == ("트래블룩",) and out["sources"] == ["https://example.kr/a"]
    assert "<industry>여행</industry>" in seen["user"] and "출입국자 수 증가" in seen["user"]
    assert "'여행': _p(" in draft_tool.as_python([out])
