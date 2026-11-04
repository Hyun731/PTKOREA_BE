"""Phase 3-2 경쟁사 포지셔닝 보강: 광고 소재 믹스 — Meta가 막으면 '접근 불가'를 정상 결과로 남긴다."""
import pytest

from app.services import ad_library
from integrations.base import CallResult, ProviderError
from integrations.fetch.page import Page


def _page(text: str) -> Page:
    return Page(url="u", final_url="u", title="t", text=text, content_hash="h")


@pytest.fixture(autouse=True)
def _reset():
    yield
    ad_library.FETCH_PAGE.clear()
    ad_library.STRUCTURED.clear()


def test_provider_error_is_reported_as_unavailable():
    def boom(url):
        raise ProviderError("SOURCE_UNAVAILABLE", "원문 접근 실패 (403)", 403)

    ad_library.FETCH_PAGE.append(boom)
    out = ad_library.fetch_ad_mix("경쟁X")
    assert out["status"] == "unavailable" and "403" in out["reason"]


def test_bot_challenge_page_is_reported_as_unavailable():
    ad_library.FETCH_PAGE.append(lambda url: _page("(function(){ executeChallenge(); })()"))
    assert ad_library.fetch_ad_mix("경쟁X")["status"] == "unavailable"


def test_login_wall_is_reported_as_unavailable():
    ad_library.FETCH_PAGE.append(lambda url: _page("로그인 후 이용해 주세요 " * 20))
    assert ad_library.fetch_ad_mix("경쟁X")["status"] == "unavailable"


def test_usable_page_is_classified_into_a_mix():
    ad_library.FETCH_PAGE.append(lambda url: _page("실제 광고 소재 설명 텍스트 " * 50))
    ad_library.STRUCTURED.append(lambda *a, **k: CallResult(
        data={"ad_count": 10, "review": 4, "influencer": 3, "product": 3}, cost_usd=0.001))
    out = ad_library.fetch_ad_mix("경쟁X")
    assert out["status"] == "ok"
    assert out["mix"] == {"review": 40, "influencer": 30, "product": 30}
    assert out["ad_count"] == 10


def test_zero_ads_found_is_unavailable():
    ad_library.FETCH_PAGE.append(lambda url: _page("실제 텍스트가 길게 있지만 광고는 없음 " * 50))
    ad_library.STRUCTURED.append(lambda *a, **k: CallResult(
        data={"ad_count": 0, "review": 0, "influencer": 0, "product": 0}, cost_usd=0.001))
    assert ad_library.fetch_ad_mix("경쟁X")["status"] == "unavailable"
