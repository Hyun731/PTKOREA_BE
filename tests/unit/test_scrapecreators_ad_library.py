"""P2-9 광고 라이브러리 파서. 픽스처는 2026-11-11 실제 응답(쌤소나이트)을 줄인 것 — 필드 이름은 그대로,
이미지 주소만 example.invalid로 바꿨다."""
import json
from pathlib import Path

import httpx
import pytest

from integrations.scrapecreators import client as sc

FX = Path(__file__).resolve().parents[1] / "fixtures" / "scrapecreators"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


def serve(name: str, seen: list):
    body = json.loads((FX / f"{name}.json").read_text())

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=body)
    return httpx.MockTransport(h)


def test_facebook_company_search_and_ads():
    seen = []
    r = sc.facebook_ad_companies("Samsonite Korea", transport=serve("facebook_ad_companies", seen))
    assert seen[0].url.path == "/v1/facebook/adLibrary/search/companies"
    korea = r.data["pages"][-1]
    assert korea == {"page_id": "138688432858063", "name": "Korea Samsonite", "country": None, "likes": 149888,
                     "ig_username": "samsonite_korea", "alias": "KoreaSamsonite", "verified": False}
    r = sc.facebook_company_ads("138688432858063", transport=serve("facebook_company_ads", seen))
    assert seen[1].url.path == "/v1/facebook/adLibrary/company/ads"
    assert seen[1].url.params["pageId"] == "138688432858063" and seen[1].url.params["country"] == "KR"
    ads = r.data["ads"]
    assert len(ads) == 4 and r.usage == {"credits": 1}
    video = ads[0]
    assert video["format"] == "video" and video["text"].startswith("#광고 평소 다양한 공간을")
    assert video["image_url"] == "https://example.invalid/preview.jpg" and video["start"] == "2026-11-02"
    assert video["url"] == "https://www.facebook.com/ads/library?id=981783581667395"
    dpa = ads[1]
    assert "{{" not in dpa["text"] and dpa["format"] == "dpa"  # 카탈로그 자리표시자는 본문으로 쓰지 않는다
    image = ads[2]
    assert image["format"] == "image" and image["text"].startswith("쌤소나이트 [쌤소나이트 11월 Special Offer]")
    assert image["image_url"] == "https://example.invalid/img.jpg"


def test_tiktok_ad_library_search_reads_title_and_dates():
    seen = []
    r = sc.tiktok_ad_library_search("Samsonite", transport=serve("tiktok_ad_library", seen))
    assert seen[0].url.path == "/v1/tiktok/ad-library/search" and "region" not in seen[0].url.params
    first = r.data["ads"][0]
    assert first["advertiser"] == "Samsonite Europe" and first["text"] == "Borse Samsonite, inarrestabili."
    assert first["start"] == "2026-10-01" and first["url"].startswith("https://library.tiktok.com/ads/detail/")
    assert r.data["has_more"] is True


def test_google_advertisers_and_company_ads():
    seen = []
    r = sc.google_ad_advertisers("쌤소나이트", transport=serve("google_ad_advertisers", seen))
    assert seen[0].url.path == "/v1/google/adLibrary/advertisers/search"
    assert r.data["advertisers"][0] == {"advertiser_id": "AR17689708705710342145", "name": "쌤소나이트코리아(주)",
                                        "region": "KR", "ads_estimate": 200}
    r = sc.google_company_ads("AR12586396129010122753", transport=serve("google_company_ads", seen))
    assert seen[1].url.params["advertiser_id"] == "AR12586396129010122753" and seen[1].url.params["region"] == "KR"
    ads = r.data["ads"]
    assert [a["format"] for a in ads] == ["video", "image", "text", "image"]
    assert ads[1]["image_url"].startswith("https://tpc.googlesyndication.com/") and ads[1]["start"] == "2026-11-10"
    assert ads[0]["image_url"] is None and ads[0]["text"] == ""


def test_facebook_ad_search_finds_korean_ads_and_their_pages():
    seen = []
    r = sc.facebook_ad_search("노스페이스", transport=serve("facebook_ad_search", seen))
    assert seen[0].url.path == "/v1/facebook/adLibrary/search/ads"
    assert seen[0].url.params["query"] == "노스페이스" and seen[0].url.params["country"] == "KR"
    ads = r.data["ads"]
    assert [a["advertiser"] for a in ads] == ["노스페이스 (The North Face)", "노스페이스 (The North Face)", "아워로그",
                                              "The North Face White Label"]
    assert ads[0]["page_id"] == "140996759295005" and ads[0]["start"] == "2026-11-08"
    assert r.data["cursor"] and r.data["total"] == 494
