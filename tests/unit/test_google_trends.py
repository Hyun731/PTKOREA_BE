"""Phase 3-4 검색 추이(Google Trends): 가짜 응답으로 — 상대 지수·연관 검색어를 읽고, 막히면 조용히 실패한다."""
import json

import httpx
import pytest

from integrations.base import ProviderError
from integrations.google_trends.client import search_trend

EXPLORE_BODY = json.dumps({
    "widgets": [
        {"id": "TIMESERIES", "request": {"time": "today 12-m"}, "token": "tok-timeseries"},
        {"id": "RELATED_QUERIES", "request": {}, "token": "tok-related"},
    ]
})
MULTILINE_BODY = json.dumps({
    "default": {"timelineData": [
        {"time": "1700000000", "value": [45, 30]},
        {"time": "1700604800", "value": [55, 40]},
    ]}
})
RELATED_BODY = json.dumps({
    "default": {"rankedList": [{"rankedKeyword": [{"query": "나이키 운동화", "value": 100},
                                                  {"query": "나이키 신상", "value": 80}]}]}
})


def _ok_handler(explore=EXPLORE_BODY, multiline=MULTILINE_BODY, related=RELATED_BODY):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/explore"):
            return httpx.Response(200, text=")]}',\n" + explore)
        if path.endswith("/widgetdata/multiline"):
            return httpx.Response(200, text=")]}',\n" + multiline)
        if path.endswith("/widgetdata/relatedsearches"):
            return httpx.Response(200, text=")]}',\n" + related)
        return httpx.Response(404)
    return handler


def test_returns_points_and_related_queries_on_success():
    res = search_trend(["나이키", "운동화"], transport=httpx.MockTransport(_ok_handler()))
    assert res.data["points"] == [
        {"time": 1700000000, "values": {"나이키": 45, "운동화": 30}},
        {"time": 1700604800, "values": {"나이키": 55, "운동화": 40}},
    ]
    assert res.data["related_queries"] == ["나이키 운동화", "나이키 신상"]
    assert res.data["geo"] == "KR"


def test_a_blocked_explore_call_raises_rate_limited():
    def blocked(request):
        return httpx.Response(429, text="too many requests")

    with pytest.raises(ProviderError) as e:
        search_trend(["나이키"], transport=httpx.MockTransport(blocked))
    assert e.value.code == "RATE_LIMITED"


def test_a_server_error_raises_source_unavailable():
    def failing(request):
        return httpx.Response(500, text="error")

    with pytest.raises(ProviderError) as e:
        search_trend(["나이키"], transport=httpx.MockTransport(failing))
    assert e.value.code == "SOURCE_UNAVAILABLE"


def test_related_queries_failure_does_not_sink_the_whole_call():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/explore"):
            return httpx.Response(200, text=")]}',\n" + EXPLORE_BODY)
        if path.endswith("/widgetdata/multiline"):
            return httpx.Response(200, text=")]}',\n" + MULTILINE_BODY)
        if path.endswith("/widgetdata/relatedsearches"):
            return httpx.Response(429, text="too many requests")
        return httpx.Response(404)

    res = search_trend(["나이키"], transport=httpx.MockTransport(handler))
    assert res.data["points"] and res.data["related_queries"] == []


def test_missing_timeseries_widget_raises_invalid_response():
    no_timeseries = json.dumps({"widgets": [{"id": "RELATED_QUERIES", "request": {}, "token": "t"}]})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=")]}',\n" + no_timeseries)

    with pytest.raises(ProviderError) as e:
        search_trend(["나이키"], transport=httpx.MockTransport(handler))
    assert e.value.code == "INVALID_RESPONSE"


def test_keyword_count_is_validated():
    with pytest.raises(ValueError):
        search_trend([])
    with pytest.raises(ValueError):
        search_trend(["a", "b", "c", "d", "e", "f"])
