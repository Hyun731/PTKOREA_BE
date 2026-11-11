"""P2-6 공식 계정 6채널 ScrapeCreators 파서. 픽스처는 2026-11-11 실제 응답(nike)을 줄인 것
(tests/fixtures/scrapecreators/*.json) — 필드 이름은 그대로다."""
import json
from pathlib import Path

import httpx
import pytest

from integrations.base import ProviderError
from integrations.scrapecreators import client as sc

FX = Path(__file__).resolve().parents[1] / "fixtures" / "scrapecreators"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


def fixture(name: str) -> dict:
    return json.loads((FX / f"{name}.json").read_text())


def serve(body: dict, seen: list, status: int = 200):
    def h(req):
        seen.append(req)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(h)


def test_tiktok_profile_and_videos():
    seen = []
    r = sc.tiktok_profile("@nike", transport=serve(fixture("tiktok_profile"), seen))
    assert seen[0].url.path == "/v1/tiktok/profile" and seen[0].url.params["handle"] == "nike"
    assert seen[0].headers["x-api-key"] == "test-key"
    assert r.data == {"followers": 9376144, "videos": 1119, "name": "Nike"} and r.usage == {"credits": 1}
    r = sc.tiktok_profile_videos("nike", max_cursor="123", transport=serve(fixture("tiktok_videos"), seen))
    assert seen[1].url.path == "/v3/tiktok/profile/videos" and seen[1].url.params["max_cursor"] == "123"
    first = r.data["posts"][0]
    assert first["posted_at"] == "2026-11-10" and first["views"] == 14910 and first["likes"] == 301
    assert first["comments"] == 13 and first["shares"] == 6 and first["saves"] == 8 and first["pinned"] is False
    assert first["url"] == "https://www.tiktok.com/@nike/photo/7706598443791158541"  # 추적 쿼리는 뺀다
    assert r.data["cursor"] == "1793126508000" and r.data["has_more"] is True


def test_tiktok_private_account_is_unavailable():
    body = fixture("tiktok_profile")
    body["user"]["privateAccount"] = True
    with pytest.raises(ProviderError) as e:
        sc.tiktok_profile("x", transport=serve(body, []))
    assert e.value.code == "SOURCE_UNAVAILABLE" and "비공개" in e.value.message


def test_facebook_profile_and_posts():
    seen = []
    r = sc.facebook_profile("https://www.facebook.com/nike", transport=serve(fixture("facebook_profile"), seen))
    assert r.data == {"followers": 39488892, "name": "Nike"}
    r = sc.facebook_profile_posts("https://www.facebook.com/nike", cursor="c1", transport=serve(fixture("facebook_posts"), seen))
    assert seen[1].url.path == "/v1/facebook/profile/posts" and seen[1].url.params["cursor"] == "c1"
    p = r.data["posts"][0]
    assert p["posted_at"] == "2024-09-04" and p["likes"] == 5096 and p["comments"] == 489 and p["shares"] == 358
    assert p["views"] is None and r.data["cursor"]


def test_x_profile_and_popular_tweets():
    seen = []
    r = sc.twitter_profile("Nike", transport=serve(fixture("twitter_profile"), seen))
    assert r.data == {"followers": 9491387, "name": "Nike"}
    r = sc.twitter_user_tweets("Nike", transport=serve(fixture("twitter_tweets"), seen))
    t = r.data["posts"][0]
    assert t["posted_at"] == "2026-10-29" and t["likes"] == 478 and t["shares"] == 142 and t["comments"] == 52
    assert t["views"] == 93169 and t["url"].startswith("https://x.com/Nike/status/")


def test_x_protected_account_is_unavailable():
    body = fixture("twitter_profile")
    body["legacy"]["protected"] = True
    with pytest.raises(ProviderError) as e:
        sc.twitter_profile("x", transport=serve(body, []))
    assert e.value.code == "SOURCE_UNAVAILABLE"


def test_threads_profile_and_posts():
    seen = []
    r = sc.threads_profile("nike", transport=serve(fixture("threads_profile"), seen))
    assert r.data == {"followers": 15216014, "name": "nike"}
    r = sc.threads_user_posts("nike", transport=serve(fixture("threads_posts"), seen))
    p = r.data["posts"][0]
    assert p["posted_at"] == "2026-10-29" and p["likes"] == 161 and p["comments"] == 5 and p["shares"] == 11
    assert p["url"] == "https://www.threads.com/@nike/post/DfEBM-2iUVI"


def test_youtube_channel_shorts():
    seen = []
    r = sc.youtube_channel_shorts(handle="@nike", transport=serve(fixture("youtube_shorts"), seen))
    assert seen[0].url.path == "/v1/youtube/channel/shorts" and seen[0].url.params["handle"] == "nike"
    s = r.data["shorts"][0]
    assert s["published_at"] == "2026-11-06" and s["views"] == 1126 and s["likes"] == 60 and s["comments"] == 3
    assert r.data["continuation_token"]


def test_missing_account_is_unavailable():
    with pytest.raises(ProviderError) as e:
        sc.threads_profile("gone", transport=serve({"success": True, "credits_charged": 1}, []))
    assert e.value.code == "SOURCE_UNAVAILABLE"
    with pytest.raises(ProviderError) as e:
        sc.facebook_profile("https://www.facebook.com/gone", transport=serve({"error": "not found"}, [], status=404))
    assert e.value.code == "SOURCE_UNAVAILABLE"
