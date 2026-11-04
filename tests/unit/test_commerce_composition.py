"""Phase 2 커머스 리뷰 — CM1(판매·리뷰 자산)·CM2(경쟁사 리뷰 비교): 채택된 스냅샷·키워드만 쓰고,
체험단·협찬은 이미 집계에서 빠져 있으므로 여기서 다시 거를 것이 없다. 자사끼리는 비교하지 않는다."""
from datetime import date

from core.composition.commerce import competitor_review_page, review_asset_page
from core.schemas.materials import ReviewKeywordRef, ReviewSnapshotRef


def _kw(sentiment="positive", keyword="쿠션감", sample_size=3, blocks_purchase=False, status="accepted",
       quote="쿠션감이 좋아요", posted_at="2026-08-01") -> ReviewKeywordRef:
    return ReviewKeywordRef(id="RK1", sentiment=sentiment, keyword=keyword, sample_size=sample_size,
                            method="AI가 분류", quotes=[{"text": quote, "posted_at": posted_at}],
                            blocks_purchase=blocks_purchase, review_status=status)


def _snap(role="self", entity="나이키", status="accepted", access="ok", rating=4.5, review_count=120,
         keywords=None, platform="musinsa", product_name="에어맥스 95") -> ReviewSnapshotRef:
    return ReviewSnapshotRef(id="REV1", brand_id="B1", entity=entity, role=role, platform=platform,
                             product_name=product_name, product_url="https://musinsa.com/products/1",
                             access_status=access, rating=rating, rating_scale=5.0, review_count=review_count,
                             measured_at=date(2026, 9, 1), review_status=status, keywords=keywords or [])


def test_review_asset_page_shows_self_platform_rating_and_keywords():
    snap = _snap(keywords=[_kw("positive", "쿠션감"), _kw("negative", "사이즈", blocks_purchase=True)])
    slides = review_asset_page([snap], "나이키")
    assert len(slides) == 1 and slides[0].slide_id == "CM1"
    table = next(b for b in slides[0].blocks if b.block_id == "table")
    row = table.rows[0]
    pos_text = row.cells[2].paragraphs[0].plain()
    neg_text = " ".join(p.plain() for p in row.cells[3].paragraphs)
    assert "쿠션감" in pos_text
    assert "사이즈" in neg_text and "구매 방해" in neg_text


def test_review_asset_page_ignores_candidate_rows_and_competitor_rows():
    candidate = _snap(status="candidate")
    competitor = _snap(role="competitor", entity="아디다스")
    assert review_asset_page([candidate], "나이키") == []
    assert review_asset_page([competitor], "나이키") == []


def test_review_asset_page_shows_unavailable_access_without_rating():
    snap = _snap(access="unavailable", rating=None, review_count=None)
    slides = review_asset_page([snap], "나이키")
    table = next(b for b in slides[0].blocks if b.block_id == "table")
    assert "평점" not in table.rows[0].cells[1].paragraphs[0].plain()  # access_status 문구만, 숫자는 없음


def test_competitor_review_page_only_shows_competitor_negative_keywords():
    comp = _snap(role="competitor", entity="아디다스",
                keywords=[_kw("positive", "디자인"), _kw("negative", "배송", blocks_purchase=False)])
    self_snap = _snap(role="self")
    slides = competitor_review_page([comp, self_snap])
    assert len(slides) == 1 and slides[0].slide_id == "CM2"
    table = next(b for b in slides[0].blocks if b.block_id == "table")
    assert len(table.rows) == 1  # 자사 행은 빠짐
    row = table.rows[0]
    assert row.cells[0].paragraphs[0].plain() == "아디다스"
    neg_text = " ".join(p.plain() for p in row.cells[3].paragraphs)
    assert "배송" in neg_text and "디자인" not in neg_text  # CM2는 부정 키워드만


def test_pages_return_empty_without_any_accepted_snapshot():
    assert review_asset_page([], "나이키") == []
    assert competitor_review_page([]) == []


def test_sponsored_excluded_keyword_still_requires_a_quote_to_be_shown():
    kw_no_quote = ReviewKeywordRef(id="RK2", sentiment="negative", keyword="배송", sample_size=2,
                                   method="AI가 분류", quotes=[], blocks_purchase=False, review_status="accepted")
    snap = _snap(keywords=[kw_no_quote])
    slides = review_asset_page([snap], "나이키")
    table = next(b for b in slides[0].blocks if b.block_id == "table")
    neg_paras = table.rows[0].cells[3].paragraphs
    assert len(neg_paras) == 1  # 키워드 줄만 있고 인용 줄은 없음(quotes가 비어 있으므로)
