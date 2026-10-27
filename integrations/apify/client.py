"""Apify Instagram Hashtag Scraper: *finds* public Instagram posts for a hashtag (PRD 6 후보 탐색).

Discovery only — which posts exist, who posted them and when. The metrics shown on slides are
still collected per post through ScrapeCreators, so one source of truth stays for the 3-1 table.
The actor has no date filter: it returns the newest posts first and the caller filters by period.
Docs: https://apify.com/apify/instagram-hashtag-scraper
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

ACTOR = os.environ.get("APIFY_ACTOR_ID") or "apify~instagram-hashtag-scraper"
PRICE_PER_RESULT = 0.0023  # actor's published pay-per-result price (USD)


def _token() -> str:
    token = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise ProviderError("PROVIDER_AUTH", "APIFY_API_TOKEN이 설정되지 않았습니다")
    return token


def _date(v) -> Optional[str]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def hashtag_posts(hashtags: list[str], *, per_tag: int = 60, transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    tags = [t.strip().lstrip("#") for t in hashtags if t.strip().lstrip("#")]
    if not tags:
        raise ValueError("hashtags required")
    body = {"hashtags": tags, "resultsType": "posts", "resultsLimit": max(1, min(200, per_tag))}
    data = request_json("Apify", "POST", f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items",
                        headers={"Authorization": f"Bearer {_token()}"}, json_body=body, timeout=280.0, max_retries=0,
                        transport=transport)
    if not isinstance(data, list):
        raise ProviderError("INVALID_RESPONSE", "Apify 응답 형식을 해석할 수 없습니다")
    posts = []
    for it in data:
        if not isinstance(it, dict) or it.get("error") or not it.get("url"):
            continue
        views = it.get("videoViewCount") or it.get("videoPlayCount")
        posts.append({
            "url": it["url"].split("?")[0], "post_id": it.get("shortCode") or it.get("id"),
            "posted_at": _date(it.get("timestamp")), "creator": it.get("ownerUsername") or "",
            "likes": it.get("likesCount") if isinstance(it.get("likesCount"), int) and it.get("likesCount") >= 0 else None,
            "comments": it.get("commentsCount"), "views": views, "type": it.get("type"),
            "caption": (it.get("caption") or "")[:300], "hashtags": it.get("hashtags") or [],
            "paid_partnership": bool(it.get("isSponsored") or it.get("paidPartnership")),
        })
    return CallResult(data={"posts": posts}, usage={"results": len(data), "hashtags": len(tags)},
                      cost_usd=round(len(data) * PRICE_PER_RESULT, 4), cost_is_estimate=True)
