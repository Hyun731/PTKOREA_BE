"""피드백 #2(자사 SNS 정량 데이터 — 댓글 감성 분석): ScrapeCreators 댓글 API 파서.
https://docs.scrapecreators.com/v2/instagram/post/comments 문서의 실제 응답 모양을 따른
합성 픽스처(실제 고객 데이터 아님)로 확인한다."""
import httpx
import pytest

from integrations.base import ProviderError
from integrations.scrapecreators.client import (
    facebook_post_comments, instagram_post_comments, tiktok_video_comments, youtube_video_comments,
)


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


@pytest.mark.parametrize(("reader", "payload", "expected"), [
    (youtube_video_comments,
     {"comments": [{"id": "y1", "content": "바퀴 소음이 커요", "publishedAt": "2026-08-01", "likeCount": 2}]},
     {"id": "y1", "text": "바퀴 소음이 커요", "posted_at": "2026-08-01", "likes": 2}),
    (tiktok_video_comments,
     {"comments": [{"cid": "t1", "text": "손잡이가 불편", "create_time": 1785542400, "digg_count": 3}]},
     {"id": "t1", "text": "손잡이가 불편", "posted_at": "2026-08-01", "likes": 3}),
    (facebook_post_comments,
     {"comments": [{"id": "f1", "message": "배송이 늦어요", "created_time": "2026-08-01T10:00:00Z",
                    "like_count": 1}]},
     {"id": "f1", "text": "배송이 늦어요", "posted_at": "2026-08-01", "likes": 1}),
])
def test_parses_other_channel_comments(reader, payload, expected):
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = reader("https://example.com/post/1", transport=httpx.MockTransport(ok))
    assert result.data["comments"] == [expected]
