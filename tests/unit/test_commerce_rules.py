"""Phase 2 커머스 리뷰 데이터 규칙: 평점·리뷰 수·키워드 저장 조건."""
from app.services.commerce import group_key, validate_keyword, validate_snapshot

VALID_SNAPSHOT = {"platform": "musinsa", "product_name": "에어맥스 95", "product_url": "https://musinsa.com/p/1",
                  "access_status": "ok", "rating": 4.5, "rating_scale": 5.0, "review_count": 120,
                  "sponsored_count": 10, "measured_at": "2026-09-01"}
VALID_KEYWORD = {"sentiment": "positive", "keyword": "쿠션감", "sample_size": 30, "method": "AI가 리뷰 본문 키워드 빈도로 집계",
                 "quotes": [{"text": "쿠션감이 좋아요", "posted_at": "2026-08-20"}]}


def test_valid_snapshot_passes():
    assert validate_snapshot(VALID_SNAPSHOT) is None


def test_unsupported_platform_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "platform": "zigzag"}) is not None


def test_missing_product_url_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "product_url": ""}) is not None


def test_rating_without_review_count_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "review_count": None}) is not None
    assert validate_snapshot({**VALID_SNAPSHOT, "review_count": 0}) is not None


def test_rating_outside_scale_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "rating": 5.5}) is not None
    assert validate_snapshot({**VALID_SNAPSHOT, "rating": -0.1}) is not None


def test_negative_review_count_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "review_count": -1}) is not None


def test_sponsored_count_over_total_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "sponsored_count": 200}) is not None


def test_missing_measured_at_is_rejected():
    assert validate_snapshot({**VALID_SNAPSHOT, "measured_at": None}) is not None


def test_unavailable_access_skips_rating_checks():
    # 로그인 벽 등으로 접근 불가 — 평점 없이도 유효한 결과.
    row = {"platform": "coupang", "product_name": "상품", "product_url": "https://coupang.com/p/1",
          "access_status": "unavailable", "measured_at": "2026-09-01"}
    assert validate_snapshot(row) is None


def test_group_key_never_mixes_platforms_or_skus():
    a = group_key("musinsa", "https://musinsa.com/p/1")
    b = group_key("29cm", "https://musinsa.com/p/1")
    c = group_key("musinsa", "https://musinsa.com/p/2-option-black")
    assert a != b and a != c  # 플랫폼이 다르거나 상품(옵션) URL이 다르면 다른 축


def test_valid_keyword_passes():
    assert validate_keyword(VALID_KEYWORD) is None


def test_keyword_without_sentiment_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "sentiment": "neutral"}) is not None


def test_keyword_without_quotes_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "quotes": []}) is not None


def test_quote_without_posted_at_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "quotes": [{"text": "좋아요", "posted_at": None}]}) is not None


def test_quote_with_blank_text_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "quotes": [{"text": "  ", "posted_at": "2026-08-20"}]}) is not None


def test_keyword_without_sample_size_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "sample_size": 0}) is not None
    assert validate_keyword({**VALID_KEYWORD, "sample_size": None}) is not None


def test_keyword_without_method_is_rejected():
    assert validate_keyword({**VALID_KEYWORD, "method": ""}) is not None
