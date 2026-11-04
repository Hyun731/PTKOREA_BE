"""Google Trends (비공식 공개 경로) — 카테고리·브랜드 키워드의 월별 상대 검색 추이와 연관 검색어
(Phase 3-4). 네이버 데이터랩과 달리 발급받는 키가 없다: trends.google.com 자신이 쓰는 공개
엔드포인트를 그대로 한 번 호출할 뿐이다.

Google이 이 경로를 자주 막는다(요청 빈도 제한) — 이는 예상된 정상 동작이다. 이 모듈은 봇 차단을
피하려는 쿠키·세션 유지, 재시도, User-Agent 위장을 하지 않는다: 한 번 평범하게 요청해 보고, 막히면
그대로 ProviderError를 돌려준다. 호출 쪽(research.py)이 이를 "수집 필요"로 조용히 남긴다.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from integrations.base import CallResult, ProviderError

EXPLORE_URL = "https://trends.google.com/trends/api/explore"
MULTILINE_URL = "https://trends.google.com/trends/api/widgetdata/multiline"
RELATED_URL = "https://trends.google.com/trends/api/widgetdata/relatedsearches"
USER_AGENT = "Mozilla/5.0 (compatible; PTK-ResearchBot/0.1; +https://example.invalid/bot)"
MAX_KEYWORDS = 5


def _parse(text: str) -> dict:
    """Google prefixes these JSON responses with ")]}'," to block simple JSON hijacking."""
    idx = text.find("{")
    if idx < 0:
        raise ProviderError("INVALID_RESPONSE", "Google Trends 응답을 읽을 수 없습니다")
    try:
        return json.loads(text[idx:])
    except json.JSONDecodeError:
        raise ProviderError("INVALID_RESPONSE", "Google Trends 응답을 읽을 수 없습니다")


def _get(client: httpx.Client, url: str, params: dict) -> dict:
    r = client.get(url, params=params)
    if r.status_code != 200:
        code = "RATE_LIMITED" if r.status_code == 429 else "SOURCE_UNAVAILABLE"
        raise ProviderError(code, f"Google Trends 접근 실패 ({r.status_code})", r.status_code)
    return _parse(r.text)


def search_trend(keywords: list[str], geo: str = "KR", timeframe: str = "today 12-m", *,
                 transport: Optional[httpx.BaseTransport] = None) -> CallResult:
    """keywords: 1~5개, Trends 자체 정규화로 서로 상대적인 0~100 지수(절대 검색량 아님).
    Returns {"points": [{"period", "values": {keyword: index}}], "related_queries": [...]}."""
    if not 1 <= len(keywords) <= MAX_KEYWORDS:
        raise ValueError(f"keywords must have 1-{MAX_KEYWORDS} items")
    req = {"comparisonItem": [{"keyword": k, "geo": geo, "time": timeframe} for k in keywords],
          "category": 0, "property": ""}
    with httpx.Client(timeout=15.0, transport=transport, headers={"User-Agent": USER_AGENT}) as client:
        explored = _get(client, EXPLORE_URL, {"hl": "ko", "tz": "-540", "req": json.dumps(req)})
        widgets = explored.get("widgets") or []
        timeline = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
        if timeline is None:
            raise ProviderError("INVALID_RESPONSE", "Google Trends 응답에 추이 위젯이 없습니다")
        tl = _get(client, MULTILINE_URL, {"req": json.dumps(timeline["request"]), "token": timeline["token"], "tz": "-540"})
        # "time" is a Unix-seconds string; a 12-month window comes back at weekly resolution, so the
        # caller aggregates into months itself rather than trusting the locale-formatted axis label.
        points = [{"time": int(pt["time"]), "values": dict(zip(keywords, pt.get("value", [])))}
                 for pt in tl.get("default", {}).get("timelineData", []) if pt.get("time")]
        related: list[str] = []
        related_widget = next((w for w in widgets if w.get("id") == "RELATED_QUERIES"), None)
        if related_widget is not None:
            try:
                rl = _get(client, RELATED_URL, {"req": json.dumps(related_widget["request"]),
                                                "token": related_widget["token"], "tz": "-540"})
                ranked = (rl.get("default", {}).get("rankedList") or [{}])[0].get("rankedKeyword") or []
                related = [kw["query"] for kw in ranked[:10] if kw.get("query")]
            except ProviderError:
                pass  # related queries are a bonus; a failure here must not sink the whole trend page
    return CallResult(data={"points": points, "related_queries": related, "geo": geo, "timeframe": timeframe},
                      usage={"requests": 2 if related else 1}, cost_usd=0.0, cost_is_estimate=False)
