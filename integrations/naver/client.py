"""Naver DataLab: 검색어트렌드(Search Trend)와 쇼핑인사이트(Shopping Insight).

Both return relative ratios normalized within one response (the response's largest value = 100) —
never an absolute search or click count. Free quota API (하루 1,000회), no per-call cost.
Keys are a Naver Developers application's Client ID/Secret; each DataLab API must be added to that
application ("API 설정"), otherwise every call answers 401 errorCode 024 even with a correct key.

Docs: https://developers.naver.com/docs/serviceapi/datalab/search/search.md
      https://developers.naver.com/docs/serviceapi/datalab/shopping/shopping.md
"""
from __future__ import annotations

import os
from datetime import date
from typing import Literal, Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

BASE = "https://openapi.naver.com/v1/datalab"
ENDPOINT = f"{BASE}/search"  # kept for callers that log the endpoint
MAX_GROUPS = 5
MAX_KEYWORDS_PER_GROUP = 20
MAX_CATEGORIES = 3  # shopping/categories: up to 3 category groups per request
MAX_SHOP_KEYWORDS = 5  # shopping/category/keywords: up to 5 keyword groups per request
SCOPE_MISSING = "024"  # Naver: "Scope Status Invalid" — the API is not added to the application

Breakdown = Literal["age", "gender", "device"]


def _keys() -> tuple[str, str]:
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ProviderError("PROVIDER_AUTH", "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되지 않았습니다")
    return client_id, client_secret


def _post(path: str, body: dict, what: str, transport: Optional[httpx.BaseTransport]) -> dict:
    client_id, client_secret = _keys()
    try:
        return request_json("Naver", "POST", f"{BASE}{path}",
                            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret,
                                     "Content-Type": "application/json"},
                            json_body=body, transport=transport)
    except ProviderError as exc:
        if exc.code == "PROVIDER_AUTH" and SCOPE_MISSING in exc.body:
            raise ProviderError("PROVIDER_AUTH", f"네이버 Developers 앱에 '데이터랩({what})' API가 추가되어 있지 않습니다 "
                                                 "— 앱 설정의 API 설정에서 추가해야 합니다", exc.status, exc.body)
        raise


def _range(start: date, end: date, time_unit: str) -> dict:
    if start > end:
        raise ValueError("start가 end보다 늦습니다")
    if time_unit not in ("date", "week", "month"):
        raise ValueError("time_unit은 date·week·month 중 하나")
    return {"startDate": start.isoformat(), "endDate": end.isoformat(), "timeUnit": time_unit}


def _filters(body: dict, device: Optional[str], ages: Optional[list[str]], gender: Optional[str]) -> dict:
    if device:
        body["device"] = device
    if ages:
        body["ages"] = ages
    if gender:
        body["gender"] = gender
    return body


def _series(results: list[dict]) -> list[dict]:
    out = []
    for r in results or []:
        points = [{"period": pt["period"], "ratio": float(pt["ratio"]), **({"group": pt["group"]} if "group" in pt else {})}
                  for pt in r.get("data") or []]
        out.append({"group": r.get("title"), "points": points})
    return out


def _result(results: list[dict], **usage) -> CallResult:
    return CallResult(data={"results": _series(results)}, usage={"requests": 1, **usage}, cost_usd=0.0,
                      cost_is_estimate=False)


def search_trend(groups: list[tuple[str, list[str]]], start: date, end: date, *, time_unit: str = "month",
                 device: Optional[str] = None, ages: Optional[list[str]] = None, gender: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """검색어트렌드. groups: up to 5 (name, keywords) pairs; each group's keywords are summed into one
    series before the ratio is computed, so synonyms/aliases belong in the same group."""
    _keys()
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError(f"groups must have 1-{MAX_GROUPS} items")
    body = _filters({**_range(start, end, time_unit),
                     "keywordGroups": [{"groupName": name, "keywords": list(dict.fromkeys(kws))[:MAX_KEYWORDS_PER_GROUP]}
                                       for name, kws in groups]}, device, ages, gender)
    data = _post("/search", body, "검색어트렌드", transport)
    return _result(data.get("results"), groups=len(groups))


def shopping_category_trend(categories: list[tuple[str, list[str]]], start: date, end: date, *,
                            time_unit: str = "month", device: Optional[str] = None,
                            ages: Optional[list[str]] = None, gender: Optional[str] = None,
                            transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """쇼핑인사이트 분야별 클릭 추이. categories: up to 3 (name, [category_id, ...]) pairs — ids are
    네이버쇼핑 분야 코드(예: 패션잡화 50000005). Ratio = click share, relative within the response."""
    _keys()
    if not 1 <= len(categories) <= MAX_CATEGORIES:
        raise ValueError(f"categories must have 1-{MAX_CATEGORIES} items")
    body = _filters({**_range(start, end, time_unit),
                     "category": [{"name": name, "param": list(ids)} for name, ids in categories]}, device, ages, gender)
    data = _post("/shopping/categories", body, "쇼핑인사이트", transport)
    return _result(data.get("results"), categories=len(categories))


def shopping_keyword_trend(category_id: str, keywords: list[tuple[str, list[str]]], start: date, end: date, *,
                           time_unit: str = "month", device: Optional[str] = None,
                           ages: Optional[list[str]] = None, gender: Optional[str] = None,
                           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """쇼핑인사이트 분야 내 키워드별 클릭 추이(예: 여행용가방 분야의 '캐리어'·'백팩'). Up to 5 groups."""
    _keys()
    if not 1 <= len(keywords) <= MAX_SHOP_KEYWORDS:
        raise ValueError(f"keywords must have 1-{MAX_SHOP_KEYWORDS} items")
    body = _filters({**_range(start, end, time_unit), "category": category_id,
                     "keyword": [{"name": name, "param": list(kws)} for name, kws in keywords]}, device, ages, gender)
    data = _post("/shopping/category/keywords", body, "쇼핑인사이트", transport)
    return _result(data.get("results"), keywords=len(keywords))


def shopping_category_breakdown(category_id: str, by: Breakdown, start: date, end: date, *, time_unit: str = "month",
                                transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """쇼핑인사이트 분야의 연령·성별·기기별 클릭 비중. Each point carries `group` (예: "20", "f", "mo")."""
    _keys()
    if by not in ("age", "gender", "device"):
        raise ValueError("by는 age·gender·device 중 하나")
    body = {**_range(start, end, time_unit), "category": category_id}
    data = _post(f"/shopping/category/{by}", body, "쇼핑인사이트", transport)
    return _result(data.get("results"), breakdown=by)


def datalab_access(*, transport: Optional[httpx.BaseTransport] = None) -> dict:
    """Which DataLab APIs this application may call: {"search": bool, "shopping": bool, "reason": str}.
    Two tiny real requests (free quota); a wrong/missing key and a missing API both read False."""
    today = date.today()
    start = date(today.year - 1, today.month, 1)
    out = {"search": False, "shopping": False, "reason": ""}
    for key, call in (("search", lambda: search_trend([("확인", ["여행"])], start, today, transport=transport)),
                      ("shopping", lambda: shopping_category_trend([("확인", ["50000000"])], start, today,
                                                                   transport=transport))):
        try:
            call()
            out[key] = True
        except ProviderError as exc:
            out["reason"] = out["reason"] or exc.message
    return out
