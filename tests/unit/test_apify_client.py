import json

import httpx

from integrations.apify.client import hashtag_posts


def test_hashtag_posts_normalizes_brand_names_for_apify(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=[])

    hashtag_posts(["#samsonite", "Samsonite (SO)", "쌤소 나이트", "samsonite"], per_tag=1,
                  transport=httpx.MockTransport(handler))

    assert seen["body"]["hashtags"] == ["samsonite", "SamsoniteSO", "쌤소나이트"]
