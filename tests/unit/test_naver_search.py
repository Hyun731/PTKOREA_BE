"""P2-3 네이버 검색 API 클라이언트 (integrations/naver/search.py) — 가짜 transport로."""
import httpx
import pytest

from integrations.base import ProviderError
from integrations.naver.search import search


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("NAVER_API_HUB_CLIENT_ID", "hub-id")
    monkeypatch.setenv("NAVER_API_HUB_CLIENT_SECRET", "hub-secret")


def _t(status, body, seen):
    def h(req):
        seen.append(req)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(h)


def test_blog_search_via_api_hub_cleans_tags_and_dates():
    seen = []
    body = {"total": 21989, "items": [{"title": "<b>샘소나이트</b> 캐리어 &amp; 후기", "link": "https://blog.naver.com/a/1",
                                       "description": "<b>샘소나이트</b> 좋아요", "bloggername": "여행 블로그",
                                       "bloggerlink": "blog.naver.com/a", "postdate": "20260501"}]}
    r = search("blog", "샘소나이트 후기", start=101, sort="sim", transport=_t(200, body, seen))
    req = seen[0]
    assert req.url.host == "naverapihub.apigw.ntruss.com" and req.url.path == "/search/v1/blog"
    assert req.url.params["start"] == "101" and req.url.params["sort"] == "sim" and req.url.params["display"] == "100"
    assert req.headers["x-ncp-apigw-api-key-id"] == "hub-id"
    item = r.data["items"][0]
    assert item == {"title": "샘소나이트 캐리어 & 후기", "url": "https://blog.naver.com/a/1", "snippet": "샘소나이트 좋아요",
                    "date": "2026-05-01", "author": "여행 블로그", "author_url": "blog.naver.com/a"}
    assert r.data["total"] == 21989 and r.data["via"] == "api_hub" and r.cost_usd == 0.0


def test_news_uses_original_link_and_pub_date_cafe_has_no_date():
    news = {"total": 1, "items": [{"title": "t", "originallink": "https://news.example/1", "link": "https://n.news.naver.com/1",
                                   "description": "d", "pubDate": "Tue, 10 Nov 2026 09:00:00 +0900"}]}
    r = search("news", "q", transport=_t(200, news, []))
    assert r.data["items"][0]["url"] == "https://news.example/1" and r.data["items"][0]["date"] == "2026-11-10"
    cafe = {"total": 1, "items": [{"title": "t", "link": "https://cafe.naver.com/x/1", "description": "d",
                                   "cafename": "여행 카페", "cafeurl": "https://cafe.naver.com/x"}]}
    item = search("cafearticle", "q", transport=_t(200, cafe, [])).data["items"][0]
    assert item["date"] is None and item["author"] == "여행 카페"


def test_inactive_api_on_api_hub_says_so():
    body = {"error": {"errorCode": 401, "message": "요청한 API는 이 Application에서 활성화되어 있지 않습니다."}}
    with pytest.raises(ProviderError) as exc:
        search("cafearticle", "q", transport=_t(401, body, []))
    assert "'카페글'" in exc.value.message and "Application" in exc.value.message


def test_developers_fallback_and_validation(monkeypatch):
    monkeypatch.delenv("NAVER_API_HUB_CLIENT_ID")
    monkeypatch.setenv("NAVER_CLIENT_ID", "d")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "s")
    seen = []
    search("kin", "q", transport=_t(200, {"total": 0, "items": []}, seen))
    assert seen[0].url.host == "openapi.naver.com" and seen[0].url.path == "/v1/search/kin.json"
    with pytest.raises(ValueError):
        search("shop", "q")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        search("blog", "q", start=1001)
