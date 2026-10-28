"""Naver DataLab 검색어트렌드 (Search Trend) API.

Returns relative search-volume ratios per keyword group, normalized within one response
(the response's largest value = 100) — never an absolute search count. Free quota API,
no per-call cost. Docs: https://developers.naver.com/docs/serviceapi/datalab/search/search.md
"""
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

ENDPOINT = "https://openapi.naver.com/v1/datalab/search"
MAX_GROUPS = 5
MAX_KEYWORDS_PER_GROUP = 20


def search_trend(groups: list[tuple[str, list[str]]], start: date, end: date, *, time_unit: str = "month",
                 device: Optional[str] = None, ages: Optional[list[str]] = None, gender: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """groups: up to 5 (name, keywords) pairs; each group's keywords are summed into one series
    before the ratio is computed, so synonyms/aliases belong in the same group."""
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ProviderError("PROVIDER_AUTH", "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되지 않았습니다")
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError(f"groups must have 1-{MAX_GROUPS} items")
    if start > end:
        raise ValueError("start가 end보다 늦습니다")
    body: dict = {
        "startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": time_unit,
        "keywordGroups": [{"groupName": name, "keywords": list(dict.fromkeys(kws))[:MAX_KEYWORDS_PER_GROUP]}
                          for name, kws in groups],
    }
    if device:
        body["device"] = device
    if ages:
        body["ages"] = ages
    if gender:
        body["gender"] = gender
    data = request_json("Naver", "POST", ENDPOINT,
                        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret,
                                 "Content-Type": "application/json"},
                        json_body=body, transport=transport)
    results = []
    for r in data.get("results") or []:
        points = [{"period": pt["period"], "ratio": float(pt["ratio"])} for pt in r.get("data") or []]
        results.append({"group": r.get("title"), "points": points})
    return CallResult(data={"results": results}, usage={"requests": 1, "groups": len(groups)},
                      cost_usd=0.0, cost_is_estimate=False)
