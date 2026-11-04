"""Phase 2 커머스 리뷰: 스마트스토어 파서 — 실제로 확인한 것은 네이버쇼핑 검색의 봇 차단
응답(418)뿐이라(검색이 막혀 실제 상품에 닿을 방법이 없었음), 성공 경로는 합성 schema.org
픽스처로 확인한다(실제 고객 데이터 아님)."""
from pathlib import Path

import httpx
import pytest

from integrations.base import ProviderError
from integrations.commerce.smartstore import fetch_product, fetch_reviews, find_product

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commerce"
PRODUCT_HTML = (FIXTURES / "generic_product.html").read_text(encoding="utf-8")
NAVER_BLOCK = (FIXTURES / "naver_block.html").read_text(encoding="utf-8")


def test_find_product_returns_none_without_a_smartstore_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no results</html>")

    assert find_product("아무 상품", transport=httpx.MockTransport(ok)) is None


def test_find_product_parses_the_first_smartstore_result_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<a href="https://smartstore.naver.com/mystore/products/123">상품</a>')

    found = find_product("아무 상품", transport=httpx.MockTransport(ok))
    assert found == {"id": "mystore/123", "url": "https://smartstore.naver.com/mystore/products/123"}


def test_find_product_raises_on_the_real_naver_block_response():
    """실제로 확인한 차단 응답(418) — ProviderError로 올라가 상위에서 접근 불가로 남는다."""
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text=NAVER_BLOCK)

    with pytest.raises(ProviderError):
        find_product("아무 상품", transport=httpx.MockTransport(blocked))


def test_fetch_product_reports_unavailable_on_the_real_naver_block():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text=NAVER_BLOCK)

    data = fetch_product("mystore/123", transport=httpx.MockTransport(blocked))
    assert data["access_status"] == "unavailable" and "418" in data["reason"]


def test_fetch_product_parses_a_successful_response():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PRODUCT_HTML)

    data = fetch_product("mystore/123", transport=httpx.MockTransport(ok))
    assert data["access_status"] == "ok" and data["product_name"] == "합성 상품 1 - 블랙"


def test_fetch_reviews_always_returns_an_empty_list():
    assert fetch_reviews("mystore/123") == []
