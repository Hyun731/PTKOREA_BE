"""P1-4 네이버 데이터랩 클라이언트 (integrations/naver/client.py) — 가짜 transport로."""
import json
from datetime import date

import httpx
import pytest

from integrations.base import ProviderError
from integrations.naver import client as naver

START, END = date(2025, 10, 1), date(2026, 9, 30)
SCOPE_ERR = {"errorMessage": "Scope Status Invalid : Authentication failed. (인증에 실패했습니다.)", "errorCode": "024"}


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("NAVER_CLIENT_ID", "id")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "secret")


def _transport(routes: dict, seen: list):
    """routes: path suffix -> (status, json body)."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content), dict(request.headers)))
        for suffix, (status, body) in routes.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"errorCode": "404"})
    return httpx.MockTransport(handler)


def _ok(title, points):
    return (200, {"results": [{"title": title, "data": points}]})


def test_search_trend_body_and_parsing():
    seen = []
    t = _transport({"/datalab/search": _ok("샘소나이트", [{"period": "2026-01-01", "ratio": 100}])}, seen)
    res = naver.search_trend([("샘소나이트", ["샘소나이트", "쌤소나이트", "샘소나이트"])], START, END, ages=["3", "4"],
                             transport=t)
    path, body, headers = seen[0]
    assert path == "/v1/datalab/search" and headers["x-naver-client-id"] == "id"
    assert body["keywordGroups"] == [{"groupName": "샘소나이트", "keywords": ["샘소나이트", "쌤소나이트"]}]
    assert body["ages"] == ["3", "4"] and body["timeUnit"] == "month"
    assert res.data == {"results": [{"group": "샘소나이트", "points": [{"period": "2026-01-01", "ratio": 100.0}]}]}
    assert res.cost_usd == 0.0


def test_missing_datalab_scope_says_what_to_enable():
    t = _transport({"/datalab/search": (401, SCOPE_ERR)}, [])
    with pytest.raises(ProviderError) as exc:
        naver.search_trend([("a", ["a"])], START, END, transport=t)
    assert exc.value.code == "PROVIDER_AUTH"
    assert "데이터랩(검색어트렌드)" in exc.value.message and "API 설정" in exc.value.message


def test_other_auth_errors_keep_the_generic_message():
    t = _transport({"/datalab/search": (401, {"errorCode": "010", "errorMessage": "invalid key"})}, [])
    with pytest.raises(ProviderError) as exc:
        naver.search_trend([("a", ["a"])], START, END, transport=t)
    assert exc.value.code == "PROVIDER_AUTH" and "데이터랩" not in exc.value.message


def test_missing_keys_fail_before_any_request(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID")
    with pytest.raises(ProviderError, match="NAVER_CLIENT_ID"):
        naver.shopping_category_trend([("a", ["1"])], START, END, transport=_transport({}, []))


def test_shopping_category_trend():
    seen = []
    t = _transport({"/shopping/categories": _ok("여행용가방", [{"period": "2026-07-01", "ratio": 100}])}, seen)
    res = naver.shopping_category_trend([("여행용가방", ["50000163"])], START, END, gender="f", transport=t)
    path, body, _ = seen[0]
    assert path == "/v1/datalab/shopping/categories"
    assert body["category"] == [{"name": "여행용가방", "param": ["50000163"]}] and body["gender"] == "f"
    assert res.data["results"][0]["points"] == [{"period": "2026-07-01", "ratio": 100.0}]


def test_shopping_keyword_trend():
    seen = []
    t = _transport({"/shopping/category/keywords": _ok("캐리어", [{"period": "2026-07-01", "ratio": 77.5}])}, seen)
    naver.shopping_keyword_trend("50000163", [("캐리어", ["캐리어", "여행가방"]), ("백팩", ["백팩"])], START, END, transport=t)
    _, body, _ = seen[0]
    assert body["category"] == "50000163"
    assert body["keyword"] == [{"name": "캐리어", "param": ["캐리어", "여행가방"]}, {"name": "백팩", "param": ["백팩"]}]


def test_shopping_breakdown_keeps_groups():
    seen = []
    points = [{"period": "2026-01-01", "group": "20", "ratio": 100}, {"period": "2026-01-01", "group": "30", "ratio": 64.2}]
    t = _transport({"/shopping/category/age": _ok("여행용가방", points)}, seen)
    res = naver.shopping_category_breakdown("50000163", "age", START, END, transport=t)
    assert seen[0][0] == "/v1/datalab/shopping/category/age"
    assert [p["group"] for p in res.data["results"][0]["points"]] == ["20", "30"]


def test_input_validation():
    t = _transport({}, [])
    with pytest.raises(ValueError):
        naver.shopping_category_trend([("a", ["1"])] * 4, START, END, transport=t)
    with pytest.raises(ValueError):
        naver.shopping_keyword_trend("1", [("a", ["a"])] * 6, START, END, transport=t)
    with pytest.raises(ValueError):
        naver.shopping_category_breakdown("1", "region", START, END, transport=t)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        naver.search_trend([("a", ["a"])], END, START, transport=t)
    with pytest.raises(ValueError):
        naver.search_trend([("a", ["a"])], START, END, time_unit="year", transport=t)


def test_datalab_access_reports_each_api():
    t = _transport({"/datalab/search": _ok("확인", []), "/shopping/categories": (401, SCOPE_ERR)}, [])
    out = naver.datalab_access(transport=t)
    assert out["search"] is True and out["shopping"] is False
    assert "쇼핑인사이트" in out["reason"]
