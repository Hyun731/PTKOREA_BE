"""피드백 #5(SNS 네이티브 검색): X·Threads 공개 게시물 키워드 검색 파서.
docs.scrapecreators.com + 실제 라이브 호출로 확인한 응답 모양을 따른 합성 픽스처(실제 고객
데이터 아님)로 확인한다."""
import httpx
import pytest

from integrations.base import ProviderError
from integrations.scrapecreators.client import threads_search, twitter_search_posts


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


def test_twitter_search_parses_text_author_date_and_likes():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True, "credits_charged": 1,
            "posts": [
                {"url": "https://x.com/foo/status/1", "views": {"count": "100"},
                 "legacy": {"created_at": "Thu Oct 01 18:50:27 +0000 2026", "full_text": "나이키 신상 괜찮네",
                           "favorite_count": 11, "retweet_count": 2},
                 "core": {"user_results": {"result": {"core": {"screen_name": "sneaker_fan"}}}}},
                {"url": "https://x.com/bar/status/2", "legacy": {"full_text": "", "created_at": None}},  # 빈 텍스트 제외
            ],
            "cursor": "2",
        })

    res = twitter_search_posts("나이키", transport=httpx.MockTransport(ok))
    assert len(res.data["posts"]) == 1
    assert res.data["posts"][0] == {"url": "https://x.com/foo/status/1", "text": "나이키 신상 괜찮네",
                                    "posted_at": "2026-10-01", "author": "sneaker_fan", "likes": 11}
    assert res.data["cursor"] == "2"


def test_twitter_search_raises_on_http_error():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "blocked"})

    with pytest.raises(ProviderError):
        twitter_search_posts("나이키", transport=httpx.MockTransport(blocked))


def test_threads_search_parses_caption_author_date_and_likes():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True, "credits_charged": 1,
            "posts": [
                {"url": "https://www.threads.com/@foo/post/abc", "caption": {"text": "나이키 운동화 득템"},
                 "taken_at": 1794222086, "like_count": 5, "user": {"username": "foo"}},
                {"url": "https://www.threads.com/@bar/post/def", "caption": {"text": ""}},  # 빈 텍스트 제외
            ],
        })

    res = threads_search("나이키", transport=httpx.MockTransport(ok))
    assert len(res.data["posts"]) == 1
    assert res.data["posts"][0] == {"url": "https://www.threads.com/@foo/post/abc", "text": "나이키 운동화 득템",
                                    "posted_at": "2026-11-09", "author": "foo", "likes": 5}


def test_threads_search_raises_on_http_error():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "blocked"})

    with pytest.raises(ProviderError):
        threads_search("나이키", transport=httpx.MockTransport(blocked))
