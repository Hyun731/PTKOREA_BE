"""Phase 2 커머스 리뷰: 무신사 파서 — 저장한 공개 HTML/JSON 픽스처 사용(실제 고객 데이터 아님)."""
import json
from pathlib import Path

import httpx
import pytest

from integrations.base import ProviderError
from integrations.commerce.musinsa import fetch_product, fetch_reviews, parse_product_page, parse_reviews

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commerce"
PRODUCT_HTML = (FIXTURES / "musinsa_product.html").read_text(encoding="utf-8")
REVIEWS_JSON = json.loads((FIXTURES / "musinsa_reviews.json").read_text(encoding="utf-8"))


def test_parse_product_page_reads_the_schema_org_json_ld():
    data = parse_product_page(PRODUCT_HTML, "https://www.musinsa.com/products/9999001")
    assert data["access_status"] == "ok"
    assert data["product_name"] == "합성 운동화 1 - 화이트"
    assert data["brand_name"] == "가상브랜드"
    assert data["rating"] == 4.7 and data["rating_scale"] == 5 and data["review_count"] == 182


def test_parse_product_page_without_ld_json_is_unavailable():
    data = parse_product_page("<html><body>no data</body></html>", "https://www.musinsa.com/products/1")
    assert data["access_status"] == "unavailable" and data["reason"]


def test_fetch_product_reports_unavailable_on_http_error():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    data = fetch_product("9999001", transport=httpx.MockTransport(blocked))
    assert data["access_status"] == "unavailable" and "403" in data["reason"]


def test_fetch_product_parses_a_successful_response():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PRODUCT_HTML)

    data = fetch_product("9999001", transport=httpx.MockTransport(ok))
    assert data["access_status"] == "ok" and data["product_name"] == "합성 운동화 1 - 화이트"


def test_parse_reviews_reads_text_rating_date_and_flags_sponsored():
    rows = parse_reviews(REVIEWS_JSON)
    assert len(rows) == 3
    assert rows[0]["rating"] == 5 and rows[0]["posted_at"] == "2026-09-10"
    assert not rows[0]["sponsored"]
    assert rows[2]["sponsored"]  # "무상 제공받아 체험단으로 작성" 고지 문구


def test_fetch_reviews_returns_empty_list_on_failure_not_an_exception():
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    assert fetch_reviews("9999001", transport=httpx.MockTransport(failing)) == []


def test_fetch_reviews_parses_a_successful_response():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=REVIEWS_JSON)

    rows = fetch_reviews("9999001", transport=httpx.MockTransport(ok))
    assert len(rows) == 3
