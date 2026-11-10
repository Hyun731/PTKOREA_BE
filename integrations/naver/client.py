"""Naver DataLab: 검색어트렌드(Search Trend)와 쇼핑인사이트(Shopping Insight).

Both return relative ratios normalized within one response (the response's largest value = 100) —
never an absolute search or click count. No per-call cost.

두 가지 키 경로가 있다 — 둘 다 요청 본문·응답 모양은 같고 주소와 헤더만 다르다.
- **NAVER API HUB** (네이버 클라우드, 2026-07-31 이후 새로 받는 키): NAVER_API_HUB_CLIENT_ID/SECRET,
  헤더 X-NCP-APIGW-API-KEY-ID/-KEY, https://naverapihub.apigw.ntruss.com/{search-trend,shopping}/v1/…
  앱(Application)에서 '검색어 트렌드'·'쇼핑인사이트'를 선택해야 한다(안 하면 401 errorCode 210).
- **네이버 Developers** (예전 키): NAVER_CLIENT_ID/SECRET, 헤더 X-Naver-Client-Id/-Secret,
  https://openapi.naver.com/v1/datalab/… 앱 'API 설정'에 데이터랩을 추가해야 한다(안 하면 024).
API HUB 키가 있으면 그것을 먼저 쓴다. Developers 키는 블로그·카페 검색 API에도 쓰이므로 그대로 둔다.

Docs: https://api.ncloud-docs.com/docs/naver-api-hub-search-trend
      https://developers.naver.com/docs/serviceapi/datalab/search/search.md
"""
from __future__ import annotations

import os
from datetime import date
from typing import Literal, NamedTuple, Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

HUB_BASE = "https://naverapihub.apigw.ntruss.com"
DEV_BASE = "https://openapi.naver.com/v1/datalab"
BASE = DEV_BASE  # kept for callers that log the endpoint
ENDPOINT = f"{DEV_BASE}/search"
MAX_GROUPS = 5
MAX_KEYWORDS_PER_GROUP = 20
MAX_CATEGORIES = 3  # shopping/categories: up to 3 category groups per request
MAX_SHOP_KEYWORDS = 5  # shopping/category/keywords: up to 5 keyword groups per request
SCOPE_MISSING = "Scope Status Invalid"  # Developers 024: the API is not added to the application
NID_AUTH = "NID AUTH Result Invalid"  # Developers 024: this application cannot use DataLab this way
HUB_NOT_SELECTED = '"210"'  # API HUB gateway: Permission Denied — the API is not selected on the application

Breakdown = Literal["age", "gender", "device"]


class Route(NamedTuple):
    via: Literal["api_hub", "developers"]
    url: str
    headers: dict


def _route(path: str) -> Route:
    """path: "/search" or "/shopping/<rest>" — mapped onto whichever key set is configured."""
    hub_id, hub_secret = os.environ.get("NAVER_API_HUB_CLIENT_ID"), os.environ.get("NAVER_API_HUB_CLIENT_SECRET")
    if hub_id and hub_secret:
        hub_path = "/search-trend/v1/search" if path == "/search" else "/shopping/v1" + path.removeprefix("/shopping")
        return Route("api_hub", HUB_BASE + hub_path, {"X-NCP-APIGW-API-KEY-ID": hub_id, "X-NCP-APIGW-API-KEY": hub_secret,
                                                     "Content-Type": "application/json"})
    dev_id, dev_secret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if dev_id and dev_secret:
        return Route("developers", DEV_BASE + path, {"X-Naver-Client-Id": dev_id, "X-Naver-Client-Secret": dev_secret,
                                                    "Content-Type": "application/json"})
    raise ProviderError("PROVIDER_AUTH", "네이버 데이터랩 키가 없습니다 — NAVER_API_HUB_CLIENT_ID/SECRET"
                                         "(또는 예전 NAVER_CLIENT_ID/SECRET)을 넣어야 합니다")


def _keys() -> Route:
    """Fail before any request when no key set is configured."""
    return _route("/search")


def _post(path: str, body: dict, what: str, transport: Optional[httpx.BaseTransport]) -> dict:
    route = _route(path)
    try:
        return request_json("Naver", "POST", route.url, headers=route.headers, json_body=body, transport=transport)
    except ProviderError as exc:
        if exc.code != "PROVIDER_AUTH":
            raise
        if route.via == "api_hub" and HUB_NOT_SELECTED in exc.body:
            msg = f"NAVER API HUB 앱에 '{what}' API가 선택되어 있지 않습니다 — 네이버 클라우드 콘솔의 Application에서 선택해야 합니다"
        elif route.via == "api_hub":
            msg = "NAVER API HUB 키 인증에 실패했습니다 — Client ID/Secret을 확인하세요"
        elif SCOPE_MISSING in exc.body:
            msg = f"네이버 Developers 앱에 '데이터랩({what})' API가 추가되어 있지 않습니다 — 앱 설정의 API 설정에서 추가해야 합니다"
        elif NID_AUTH in exc.body:
            msg = ("네이버 Developers 키로는 데이터랩을 부를 수 없습니다 — NAVER API HUB(네이버 클라우드) 키를 "
                   "NAVER_API_HUB_CLIENT_ID/SECRET에 넣어야 합니다")
        else:
            raise
        raise ProviderError("PROVIDER_AUTH", msg, exc.status, exc.body)


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
    """Which DataLab APIs these keys may call: {"search": bool, "shopping": bool, "reason": str, "via": route}.
    Two tiny real requests (free quota); a wrong/missing key and a missing API both read False."""
    today = date.today()
    start = date(today.year - 1, today.month, 1)
    out = {"search": False, "shopping": False, "reason": "", "via": None}
    try:
        out["via"] = _keys().via
    except ProviderError as exc:
        out["reason"] = exc.message
        return out
    for key, call in (("search", lambda: search_trend([("확인", ["여행"])], start, today, transport=transport)),
                      ("shopping", lambda: shopping_category_trend([("확인", ["50000000"])], start, today,
                                                                   transport=transport))):
        try:
            call()
            out[key] = True
        except ProviderError as exc:
            out["reason"] = out["reason"] or exc.message
    return out
