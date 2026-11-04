"""Phase 2 커머스 리뷰: 공용 schema.org Product/AggregateRating 추출 — 플랫폼 5개가 모두 쓴다."""
from pathlib import Path

from integrations.commerce import schema_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "commerce"
PRODUCT_HTML = (FIXTURES / "generic_product.html").read_text(encoding="utf-8")


def test_extract_product_reads_name_brand_rating_and_review_count():
    data = schema_org.extract_product(PRODUCT_HTML, "https://example.com/products/1", "musinsa")
    assert data == {"platform": "musinsa", "product_name": "합성 상품 1 - 블랙", "product_url": "https://example.com/products/1",
                    "brand_name": "가상브랜드", "rating": 4.6, "rating_scale": 5, "review_count": 231, "access_status": "ok"}


def test_extract_product_is_unavailable_without_ld_json():
    data = schema_org.extract_product("<html><body>no data</body></html>", "https://example.com/products/1", "coupang")
    assert data["access_status"] == "unavailable" and data["platform"] == "coupang" and data["reason"]


def test_extract_product_skips_non_product_ld_json_blocks():
    html = '<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>'
    data = schema_org.extract_product(html, "https://example.com/products/1", "29cm")
    assert data["access_status"] == "unavailable"
