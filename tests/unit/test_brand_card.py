"""Phase 1-1 브랜드 카드: 업종, 공식 계정(자사·경쟁사) — schema rules and pure discovery logic."""
import pytest
from pydantic import ValidationError

from app.services import industry, official_accounts
from core.schemas.project import Brand, OfficialProfile


def brand(**kw) -> Brand:
    base = {"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"]}
    return Brand.model_validate({**base, **kw})


def test_official_profile_needs_url_unless_none():
    OfficialProfile(channel="instagram", url="https://instagram.com/a")  # ok
    OfficialProfile(channel="facebook", status="none")  # ok: 운영 안 함은 URL이 없어도 됨
    with pytest.raises(ValidationError):
        OfficialProfile(channel="facebook", status="candidate", url="")


def test_industry_must_be_from_the_fixed_list():
    brand(industry="패션")
    with pytest.raises(ValidationError):
        brand(industry="아무거나")


def test_profiles_for_splits_self_and_competitors():
    b = brand(official_profiles=[{"channel": "instagram", "url": "https://instagram.com/self"}],
             competitor_profiles={"경쟁X": [{"channel": "youtube", "url": "https://youtube.com/competitorx"}]})
    assert [p.url for p in b.profiles_for("브랜드A")] == ["https://instagram.com/self"]
    assert [p.url for p in b.profiles_for("경쟁X")] == ["https://youtube.com/competitorx"]
    assert b.profiles_for("모르는 이름") == []


def test_competitor_profiles_drop_when_the_competitor_is_removed():
    b = brand(competitors=["경쟁X", "경쟁Y"],
             competitor_profiles={"경쟁X": [{"channel": "instagram", "url": "https://instagram.com/x"}],
                                  "경쟁Y": [{"channel": "instagram", "url": "https://instagram.com/y"}]})
    b2 = Brand.model_validate({**b.model_dump(), "competitors": ["경쟁X"]})
    assert set(b2.competitor_profiles) == {"경쟁X"}


def test_industry_missing_lists_brands_without_one():
    cfg = {"brands": [{"name": "브랜드A"}, {"name": "브랜드B", "industry": "뷰티"}]}
    assert industry.missing(cfg) == ["브랜드A"]


def test_official_accounts_missing_covers_self_and_competitors_without_any_entry():
    b = {"name": "브랜드A", "competitors": ["경쟁X", "경쟁Y"],
         "official_profiles": [], "competitor_profiles": {"경쟁X": [{"channel": "instagram", "url": "https://instagram.com/x"}]}}
    assert official_accounts.missing(b) == ["브랜드A", "경쟁Y"]  # 경쟁X는 이미 있어서 빠짐


def test_official_accounts_discover_rejects_urls_on_the_wrong_domain():
    assert official_accounts._valid("instagram", "https://instagram.com/brand") is True
    assert official_accounts._valid("instagram", "https://news.example.com/brand") is False


class _Ledger:
    """A RunLedger stand-in: runs fn() directly, no DB, no cache."""
    def call(self, provider, endpoint, request, est_cost, fn, cache_days=7):
        return fn()


def test_official_accounts_discover_uses_search_then_ai_judgment():
    official_accounts.SEARCH.clear()
    official_accounts.STRUCTURED.clear()
    from integrations.base import CallResult

    official_accounts.SEARCH.append(lambda qs, **kw: CallResult(
        data={"results": [{"title": "브랜드A 공식 인스타", "url": "https://instagram.com/brand_a", "snippet": "", "date": None}]},
        cost_usd=0.005))
    official_accounts.STRUCTURED.append(lambda system, user, schema, **kw: CallResult(
        data={"profiles": [{"channel": "instagram", "url": "https://instagram.com/brand_a", "confident": True}]},
        cost_usd=0.001))
    try:
        found = official_accounts.discover("브랜드A", "러기지", _Ledger())
    finally:
        official_accounts.SEARCH.clear()
        official_accounts.STRUCTURED.clear()
    assert found == [{"channel": "instagram", "url": "https://instagram.com/brand_a", "status": "candidate"}]


def test_official_accounts_discover_empty_search_returns_no_candidates():
    official_accounts.SEARCH.clear()
    from integrations.base import CallResult

    official_accounts.SEARCH.append(lambda qs, **kw: CallResult(data={"results": []}, cost_usd=0.005))
    try:
        assert official_accounts.discover("아무도모름", "기타", _Ledger()) == []
    finally:
        official_accounts.SEARCH.clear()
