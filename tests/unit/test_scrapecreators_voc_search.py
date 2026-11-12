"""P2-8 소비자 원문 채널: 틱톡 키워드 검색·유튜브 검색 파서. 픽스처는 2026-11-11 실제 응답
(샘소나이트)을 줄인 것(tests/fixtures/scrapecreators/*_search.json) — 필드 이름은 그대로다."""
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


def serve(name: str, seen: list, status: int = 200):
    body = json.loads((FX / f"{name}.json").read_text())

    def h(req):
        seen.append(req)
        return httpx.Response(status, json=body)
    return httpx.MockTransport(h)


def test_tiktok_search_keyword_reads_caption_author_date_and_counts():
    seen = []
    r = sc.tiktok_search_keyword("샘소나이트 후기", transport=serve("tiktok_search", seen))
    assert seen[0].url.path == "/v1/tiktok/search/keyword"
    assert seen[0].url.params["query"] == "샘소나이트 후기" and seen[0].url.params["region"] == "KR"
    posts = r.data["posts"]
    assert len(posts) == 4 and r.usage == {"credits": 1} and r.data["has_more"] is True
    kr = posts[1]
    assert kr["url"] == "https://www.tiktok.com/@honey_gallery/video/7555836159457299719"  # 공유용 쿼리 없이
    assert kr["text"].startswith("요즘 이 캐리어가 화제인 이유") and kr["region"] == "KR"
    assert kr["posted_at"] == "2025-09-30" and kr["author"] == "honey_gallery" and kr["followers"] == 63998
    assert kr["views"] == 1931 and kr["likes"] == 17 and kr["comments"] == 1 and kr["sponsored"] is False


def test_youtube_search_reads_videos_and_shorts():
    seen = []
    r = sc.youtube_search("샘소나이트 후기", transport=serve("youtube_search", seen))
    assert seen[0].url.path == "/v1/youtube/search" and seen[0].url.params["query"] == "샘소나이트 후기"
    videos = r.data["videos"]
    assert len(videos) == 5
    first = videos[0]
    assert first == {"url": "https://www.youtube.com/watch?v=wgOJOka9A7A",
                     "title": "더 이상 고민하지마세요! 샘소나이트백팩 한번에 몰아보기!", "posted_at": "2024-11-11",
                     "author": "솔직한 리뷰", "views": 11655, "is_short": False}
    short = videos[-1]
    assert short["is_short"] is True and short["posted_at"] is None  # 쇼츠는 게시일이 오지 않는다


def test_search_errors_raise_provider_error():
    with pytest.raises(ProviderError):
        sc.youtube_search("x", transport=serve("youtube_search", [], status=500))
