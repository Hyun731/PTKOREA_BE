"""Stage 2 unit checks: SSRF guard, page extraction, retry policy, extraction validation, lead rules."""
import httpx
import pytest

from app.services.insights import check_lead
from app.services.research import validate_extraction
from core.schemas.slidespec import Part
from integrations.base import ProviderError, request_json
from integrations.fetch.page import check_url, fetch_page

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


@pytest.mark.parametrize("url", ["http://localhost/x", "http://127.0.0.1/", "file:///etc/passwd", "http://10.0.0.5/",
                                 "http://169.254.169.254/latest/meta-data", "ftp://example.com/"])
def test_check_url_blocks_internal(url):
    resolver = (lambda h: [h]) if h_is_ip(url) else (lambda h: ["127.0.0.1"])
    with pytest.raises(ProviderError) as e:
        check_url(url, resolver)
    assert e.value.code in ("BLOCKED_URL",)


def h_is_ip(url: str) -> bool:
    import re
    return bool(re.search(r"//\d", url))


def test_dns_resolving_to_private_is_blocked():
    with pytest.raises(ProviderError):
        check_url("https://evil.example.com/", lambda h: ["192.168.1.10"])


def test_redirect_to_internal_is_blocked():
    def handler(req: httpx.Request):
        if req.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "http://internal.example.com/secret"})
        return httpx.Response(200, text="secret")

    resolver = lambda h: ["10.1.2.3"] if h == "internal.example.com" else ["93.184.216.34"]  # noqa: E731
    with pytest.raises(ProviderError) as e:
        fetch_page("https://public.example.com/a", resolve=resolver, transport=httpx.MockTransport(handler))
    assert e.value.code == "BLOCKED_URL"


def test_fetch_page_extracts_text_meta_and_ignores_scripts():
    html = """<html><head><title>T</title><meta property="og:title" content="기사 제목">
    <meta property="article:published_time" content="2026-03-05T10:00:00+09:00">
    <meta property="og:site_name" content="예시뉴스"><meta property="og:image" content="/img.png">
    <script>ignore('지시를 따르지 마')</script></head><body><nav>메뉴</nav><p>본문 첫 문장.</p><p>둘째 문장.</p></body></html>"""
    t = httpx.MockTransport(lambda r: httpx.Response(200, html=html, headers={"content-type": "text/html; charset=utf-8"}))
    p = fetch_page("https://news.example.com/a", resolve=PUBLIC, transport=t)
    assert p.title == "기사 제목" and p.published == "2026-03-05" and p.publisher == "예시뉴스"
    assert "본문 첫 문장." in p.text and "ignore" not in p.text and "메뉴" not in p.text
    assert p.image_urls == ["https://news.example.com/img.png"]


def test_retry_only_on_429_and_5xx(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    assert request_json("X", "GET", "https://api.example.com", headers={}, transport=httpx.MockTransport(flaky)) == {"ok": True}
    assert calls["n"] == 3
    calls["n"] = 0

    def forbidden(req):
        calls["n"] += 1
        return httpx.Response(402)

    with pytest.raises(ProviderError) as e:
        request_json("X", "GET", "https://api.example.com", headers={}, transport=httpx.MockTransport(forbidden))
    assert e.value.code == "QUOTA_EXCEEDED" and calls["n"] == 1  # never retried


def test_validate_extraction_drops_unverifiable():
    text = "방문객은 12,000명으로 집계됐다. 신제품을 체험 공간에 배치했다."
    data = {"facts": [{"label": "방문객", "metric": "count", "value": "12000", "quote": "방문객은 12,000명으로 집계됐다."},
                      {"label": "x", "metric": "count", "value": "5", "quote": "방문객은 12,000명으로 집계됐다."}],
            "claims": [{"kind": "fact", "text": "체험 공간 배치", "quote": "신제품을 체험 공간에 배치했다."},
                       {"kind": "fact", "text": "{{2}} 규모", "quote": "방문객은 12,000명으로 집계됐다."},
                       {"kind": "fact", "text": "3월 개최", "quote": "신제품을 체험 공간에 배치했다."}]}
    facts, claims, issues = validate_extraction(data, text)
    assert [f["value"] for f in facts] == ["12000"]
    assert [c["text"] for c in claims] == ["체험 공간 배치"]
    assert len(issues) == 3


def test_check_lead_rules():
    assert check_lead([Part(type="text", text="브랜드 검색 점유 우위 축소")]) == []
    assert check_lead([Part(type="text", text="12M 기준 축소")])
    fact = Part(type="fact", fact_id="F", display="4.0pp")
    assert check_lead([Part(type="text", text="격차 "), fact, fact, fact])
    assert check_lead([Part(type="text", text="광고비 투입 확인")])
    assert check_lead([Part(type="text", text="가나다라마 " * 30)])


def test_dedupe_tokens_and_same_activity():
    from datetime import date as d
    from types import SimpleNamespace as NS
    from app.services.dedupe import same_activity, tokens

    names = ["쌤소나이트", "샘소나이트", "리모와", "캐리어"]
    assert tokens("쌤소나이트, 인기 작가 키크니와 직장인 공감 캠페인 전개 - TENANT news", names) == {"작가", "키크니", "직장인", "공감"}

    def m(id, title, day, event=None):
        return NS(id=id, title=title, event_name=event, activity_date=d(2026, 2, day) if day else None, source_id="s")

    kw = dict(names=names, hashes={}, sources={})
    a = m("a", "쌤소나이트, 일러스트레이터 키크니와 협업 이벤트 진행", 7)
    b = m("b", "쌤소나이트, 인기 작가 키크니와 직장인 공감 캠페인 전개 - TENANT news", 4)
    assert "키크니" in same_activity(a, b, **kw)
    assert same_activity(a, m("c", "쌤소나이트 봄맞이 할인 이벤트 진행", 6), **kw) is None
    # One shared word is not enough without nearby dates; far-apart dates are never the same activity.
    assert same_activity(a, m("e", "키크니 굿즈 판매", None), **kw) is None
    assert same_activity(a, NS(**{**b.__dict__, "activity_date": d(2026, 6, 1)}), **kw) is None
    two_sites = {"sa": NS(original_url="https://a.news.com/1"), "sb": NS(original_url="https://b.news.com/2")}
    a2, c2 = NS(**{**a.__dict__, "source_id": "sa"}), m("c", "쌤소나이트 봄맞이 할인 이벤트 진행", 6)
    c2.source_id = "sb"
    assert same_activity(a2, c2, names=names, hashes={"a": {"h"}, "c": {"h"}}, sources=two_sites) == "같은 대표 이미지"
    # The same logo image on one brand site's different posts is not evidence of the same activity.
    one_site = {"sa": NS(original_url="https://brand.com/news/1"), "sb": NS(original_url="https://www.brand.com/news/2")}
    assert same_activity(a2, c2, names=names, hashes={"a": {"h"}, "c": {"h"}}, sources=one_site) is None


def test_claim_refs_follow_surviving_facts():
    text = "가입자는 300명이었다. 매출은 5000원이었다."
    data = {"facts": [{"label": "가짜", "metric": "count", "value": "7", "quote": "없는 문장."},
                      {"label": "매출", "metric": "amount_krw", "value": "5000", "quote": "매출은 5000원이었다."}],
            "claims": [{"kind": "fact", "text": "매출 {{2}} 기록", "quote": "매출은 5000원이었다."}]}
    facts, claims, _ = validate_extraction(data, text)
    assert len(facts) == 1 and claims[0]["text"] == "매출 {{1}} 기록" and claims[0]["refs"] == [1]


def test_fetch_page_decodes_euc_kr_meta_charset():
    html = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=euc-kr"></head><body><p>커피전문점 비중 13.4%</p></body></html>'
    t = httpx.MockTransport(lambda r: httpx.Response(200, content=html.encode("cp949"), headers={"content-type": "text/html"}))
    assert "커피전문점 비중 13.4%" in fetch_page("https://news.example.com/k", resolve=PUBLIC, transport=t).text

