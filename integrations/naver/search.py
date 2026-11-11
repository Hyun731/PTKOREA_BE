"""네이버 검색 API: 블로그·카페글·뉴스·지식iN (P2-3 소비자 원문·언급량).

NAVER API HUB(네이버 클라우드) 키를 먼저 쓴다 — GET https://naverapihub.apigw.ntruss.com/search/v1/{kind}.
API HUB 앱에서 API마다 활성화해야 한다(안 하면 401 "요청한 API는 이 Application에서 활성화되어 있지
않습니다"). 2026-11-11 기준 블로그·뉴스·지식iN은 활성, 카페글은 비활성. 하루 25,000회, 비용 없음.
API HUB 키가 없으면 예전 Developers 키로 https://openapi.naver.com/v1/search/{kind}.json.

결과의 title·description에는 검색어 강조 태그(<b>)가 들어 있어 벗겨서 돌려준다. 블로그는 작성일
(postdate, yyyymmdd)이 있고 카페글·지식iN에는 날짜가 없다. 뉴스는 pubDate(RFC 822).
"""
from __future__ import annotations

import html
import os
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Optional

import httpx

from integrations.base import CallResult, ProviderError, request_json

HUB = "https://naverapihub.apigw.ntruss.com/search/v1"
DEV = "https://openapi.naver.com/v1/search"
Kind = Literal["blog", "cafearticle", "news", "kin"]
KIND_LABEL = {"blog": "블로그", "cafearticle": "카페글", "news": "뉴스", "kin": "지식iN"}
MAX_DISPLAY = 100
MAX_START = 1000
TAG = re.compile(r"</?b>")


def _route(kind: Kind) -> tuple[str, str, dict]:
    hub_id, hub_secret = os.environ.get("NAVER_API_HUB_CLIENT_ID"), os.environ.get("NAVER_API_HUB_CLIENT_SECRET")
    if hub_id and hub_secret:
        return "api_hub", f"{HUB}/{kind}", {"X-NCP-APIGW-API-KEY-ID": hub_id, "X-NCP-APIGW-API-KEY": hub_secret}
    dev_id, dev_secret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if dev_id and dev_secret:
        return "developers", f"{DEV}/{kind}.json", {"X-Naver-Client-Id": dev_id, "X-Naver-Client-Secret": dev_secret}
    raise ProviderError("PROVIDER_AUTH", "네이버 검색 키가 없습니다 — NAVER_API_HUB_CLIENT_ID/SECRET을 넣어야 합니다")


def _clean(text: Optional[str]) -> str:
    return html.unescape(TAG.sub("", text or "")).strip()


def _date(item: dict, kind: Kind) -> Optional[date]:
    if kind == "blog" and item.get("postdate"):
        try:
            return datetime.strptime(item["postdate"], "%Y%m%d").date()
        except ValueError:
            return None
    if kind == "news" and item.get("pubDate"):
        try:
            return parsedate_to_datetime(item["pubDate"]).date()
        except (TypeError, ValueError):
            return None
    return None


def search(kind: Kind, query: str, *, display: int = MAX_DISPLAY, start: int = 1, sort: Literal["sim", "date"] = "date",
           transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """한 페이지(최대 100건). data = {"total": 전체 결과 수, "items": [{title, url, snippet, date, author, author_url}]}.
    total은 검색 결과 문서 수(누적)이지 검색량이 아니다."""
    if kind not in KIND_LABEL:
        raise ValueError(f"kind는 {', '.join(KIND_LABEL)} 중 하나")
    if not 1 <= display <= MAX_DISPLAY or not 1 <= start <= MAX_START:
        raise ValueError("display는 1~100, start는 1~1000")
    via, url, headers = _route(kind)
    try:
        data = request_json("Naver", "GET", url, headers=headers,
                            params={"query": query, "display": display, "start": start, "sort": sort},
                            transport=transport)
    except ProviderError as exc:
        if exc.code == "PROVIDER_AUTH" and via == "api_hub":
            raise ProviderError("PROVIDER_AUTH", f"NAVER API HUB 앱에서 '{KIND_LABEL[kind]}' 검색 API가 활성화되어 있지 않습니다 "
                                                 "— 네이버 클라우드 콘솔의 Application에서 선택해야 합니다",
                                exc.status, exc.body)
        raise
    items = []
    for it in data.get("items") or []:
        items.append({
            "title": _clean(it.get("title")), "url": it.get("originallink") or it.get("link"),
            "snippet": _clean(it.get("description")), "date": _date(it, kind),
            "author": it.get("bloggername") or it.get("cafename"), "author_url": it.get("bloggerlink") or it.get("cafeurl"),
        })
    return CallResult(data={"total": int(data.get("total") or 0), "items": items, "via": via},
                      usage={"requests": 1}, cost_usd=0.0, cost_is_estimate=False)
