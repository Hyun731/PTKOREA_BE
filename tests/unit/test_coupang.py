"""Phase 2 커머스 리뷰: 쿠팡 파서 — 실제로 확인한 것은 Akamai 봇 차단 응답뿐이라(사이트 전체가
막혀 있음), 성공 경로는 합성 schema.org 픽스처로 확인한다(실제 고객 데이터 아님)."""
from pathlib import Path

import httpx
import pytest

from integrations.base import ProviderError
from integrations.commerce.coupang import fetch_product, fetch_reviews, find_product

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commerce"
PRODUCT_HTML = (FIXTURES / "generic_product.html").read_text(encoding="utf-8")
AKAMAI_BLOCK = (FIXTURES / "akamai_block.html").read_text(encoding="utf-8")


def test_find_product_returns_none_without_a_product_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no results</html>")

    assert find_product("아무 상품", transport=httpx.MockTransport(ok)) is None


def test_find_product_parses_the_first_result_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<a href="/vp/products/987654">상품</a>')

    found = find_product("아무 상품", transport=httpx.MockTransport(ok))
    assert found == {"id": "987654", "url": "https://www.coupang.com/vp/products/987654"}


def test_find_product_raises_on_real_akamai_block_response():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=AKAMAI_BLOCK)

    with pytest.raises(ProviderError):
        find_product("아무 상품", transport=httpx.MockTransport(blocked))


def test_fetch_product_reports_unavailable_on_the_real_akamai_block():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=AKAMAI_BLOCK)

    data = fetch_product("987654", transport=httpx.MockTransport(blocked))
    assert data["access_status"] == "unavailable" and "403" in data["reason"]


def test_fetch_product_parses_a_successful_response():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PRODUCT_HTML)

    data = fetch_product("987654", transport=httpx.MockTransport(ok))
    assert data["access_status"] == "ok" and data["product_name"] == "합성 상품 1 - 블랙"


def test_fetch_reviews_always_returns_an_empty_list():
    assert fetch_reviews("987654") == []
