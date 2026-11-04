"""Phase 2 커머스 리뷰: 29CM 파서 — 실제로 확인한 것은 Cloudflare 봇 차단 응답뿐이라(사이트
전체가 막혀 있음), 성공 경로는 합성 schema.org 픽스처로 확인한다(실제 고객 데이터 아님)."""
from pathlib import Path

import httpx

from integrations.commerce.twentyninecm import fetch_product, fetch_reviews, find_product

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commerce"
PRODUCT_HTML = (FIXTURES / "generic_product.html").read_text(encoding="utf-8")
CLOUDFLARE_BLOCK = (FIXTURES / "cloudflare_block.html").read_text(encoding="utf-8")


def test_find_product_returns_none_without_a_product_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no results</html>")

    assert find_product("아무 상품", transport=httpx.MockTransport(ok)) is None


def test_find_product_parses_the_first_result_link():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<a href="/products/12345">상품</a>')

    found = find_product("아무 상품", transport=httpx.MockTransport(ok))
    assert found == {"id": "12345", "url": "https://www.29cm.co.kr/products/12345"}


def test_find_product_raises_on_real_cloudflare_block_response():
    """실제로 확인한 차단 응답(Cloudflare 403) — ProviderError로 올라가 상위에서 접근 불가로 남는다."""
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=CLOUDFLARE_BLOCK)

    from integrations.base import ProviderError
    import pytest
    with pytest.raises(ProviderError):
        find_product("아무 상품", transport=httpx.MockTransport(blocked))


def test_fetch_product_reports_unavailable_on_the_real_cloudflare_block():
    def blocked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=CLOUDFLARE_BLOCK)

    data = fetch_product("12345", transport=httpx.MockTransport(blocked))
    assert data["access_status"] == "unavailable" and "403" in data["reason"]


def test_fetch_product_parses_a_successful_response():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PRODUCT_HTML)

    data = fetch_product("12345", transport=httpx.MockTransport(ok))
    assert data["access_status"] == "ok" and data["product_name"] == "합성 상품 1 - 블랙"


def test_fetch_reviews_always_returns_an_empty_list():
    """공개 리뷰 API를 확인하지 못했다 — 항상 빈 목록(크래시 아님)."""
    assert fetch_reviews("12345") == []
