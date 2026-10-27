"""Perplexity Search API (POST /search). Finds candidate sources; never treated as verified facts
(PRD 6). Docs: https://docs.perplexity.ai/docs/search/quickstart"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

ENDPOINT = "https://api.perplexity.ai/search"
# Standard-search unit price not confirmed in our account yet: recorded as an estimate.
EST_COST_PER_REQUEST = 0.005


def search(queries: list[str], *, max_results: int = 5, country: str = "KR",
           languages: Optional[list[str]] = None, max_tokens_per_page: int = 1024,
           published_after: Optional[str] = None, published_before: Optional[str] = None,
           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """published_after/before: MM/DD/YYYY publish-date window (search_after/before_date_filter)."""
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise ProviderError("PROVIDER_AUTH", "PERPLEXITY_API_KEY가 설정되지 않았습니다")
    if not 1 <= len(queries) <= 5:
        raise ValueError("queries must have 1-5 items")
    body = {"query": queries if len(queries) > 1 else queries[0], "max_results": max(1, min(20, max_results)),
            "country": country, "max_tokens_per_page": max_tokens_per_page}
    if languages:
        body["search_language_filter"] = languages
    if published_after:
        body["search_after_date_filter"] = published_after
    if published_before:
        body["search_before_date_filter"] = published_before
    data = request_json("Perplexity", "POST", ENDPOINT, headers={"Authorization": f"Bearer {key}"},
                        json_body=body, transport=transport)
    results = []
    raw = data.get("results") or []
    # Multi-query responses may nest one list per query.
    flat = [r for group in raw for r in (group if isinstance(group, list) else [group])]
    for r in flat:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        results.append({"title": (r.get("title") or "").strip(), "url": r["url"], "snippet": r.get("snippet") or "",
                        "date": r.get("date"), "last_updated": r.get("last_updated")})
    return CallResult(data={"id": data.get("id"), "results": results}, usage={"requests": 1, "queries": len(queries)},
                      cost_usd=EST_COST_PER_REQUEST, cost_is_estimate=True)
