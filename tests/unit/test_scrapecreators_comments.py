"""피드백 #2(자사 SNS 정량 데이터 — 댓글 감성 분석): ScrapeCreators 댓글 API 파서.
https://docs.scrapecreators.com/v2/instagram/post/comments 문서의 실제 응답 모양을 따른
합성 픽스처(실제 고객 데이터 아님)로 확인한다."""
import httpx
import pytest

from integrations.base import ProviderError
from integrations.scrapecreators.client import instagram_post_comments


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


def test_parses_comment_text_date_and_likes():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True, "credits_charged": 1,
            "comments": [
                {"id": "c1", "text": "진짜 예뻐요 재구매각", "comment_like_count": 3, "created_at": "2026-08-01T10:00:00.000Z"},
                {"id": "c2", "text": "", "comment_like_count": 0, "created_at": "2026-08-02T10:00:00.000Z"},  # 빈 댓글 제외
                {"id": "c3", "text": "사이즈가 작아요", "comment_like_count": 0, "created_at": "2026-08-03T10:00:00.000Z"},
            ],
            "cursor": "AQH...",
        })

    res = instagram_post_comments("https://www.instagram.com/p/abc/", transport=httpx.MockTransport(ok))
    assert len(res.data["comments"]) == 2  # 빈 댓글은 빠짐
    assert res.data["comments"][0] == {"id": "c1", "text": "진짜 예뻐요 재구매각", "posted_at": "2026-08-01", "likes": 3}
    assert res.data["cursor"] == "AQH..."


def test_raises_on_http_error():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "blocked"})

    with pytest.raises(ProviderError):
        instagram_post_comments("https://www.instagram.com/p/abc/", transport=httpx.MockTransport(blocked))
