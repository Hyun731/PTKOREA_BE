"""커머스 경쟁 지표: 무신사·29CM 공개 목록 파싱, 제품군 → 카테고리, 브랜드 매칭, Fact 만들기."""
from datetime import date

from app.services import commerce_rank as cr
from core.schemas.project import Brand, Target
from integrations.commerce import musinsa, twentyninecm


def _brand(**kw) -> Brand:
    base = {"id": "SO", "name": "샘소나이트", "competitors": ["브라이튼"], "categories": ["러기지", "비즈니스 가방"],
            "aliases": ["쌤소나이트"]}
    return Brand(**{**base, **kw})


def test_parse_plp_converts_score_to_five_point_rating():
    rows = musinsa.parse_plp({"data": {"list": [
        {"goodsNo": 1, "goodsName": "A", "brand": "samsonite", "brandName": "쌤소나이트", "reviewCount": 32,
         "reviewScore": 98, "goodsLinkUrl": "https://www.musinsa.com/products/1"},
        {"goodsNo": 2, "goodsName": "B", "brand": "samsonite", "brandName": "쌤소나이트", "reviewCount": 0,
         "reviewScore": 0}]}})
    assert rows[0]["rating"] == 4.9 and rows[0]["review_count"] == 32
    assert rows[1]["rating"] is None and rows[1]["url"].endswith("/products/2")


def test_parse_rank_categories_prefers_top_level_and_skips_all():
    payload = {"tabs": [{"key": "musinsa_199_017025", "text": {"text": "가방"}},
                        {"key": "musinsa_199_004", "text": {"text": "가방"}},
                        {"key": "musinsa_199_004009", "text": {"text": "캐리어"}},
                        {"key": "musinsa_199_004000", "text": {"text": "전체"}},
                        {"key": "musinsa_200_004001", "text": {"text": "백팩"}}]}  # 신상 탭은 무시
    assert musinsa.parse_rank_categories(payload) == {"가방": "004000", "캐리어": "004009"}


def test_parse_ranking_reads_rank_and_brand():
    item = {"type": "PRODUCT_COLUMN", "id": "77", "image": {"rank": 2},
            "info": {"brandName": "브라이튼 캐리어", "productName": "웰턴 캐리어",
                     "onClickBrandName": {"eventLog": {"ga4": {"payload": {"brand_id": "brighton"}}}}}}
    rows = musinsa.parse_ranking({"data": {"modules": [{"items": [item, {"type": "BANNER"}]}]}})
    assert rows == [{"rank": 2, "id": "77", "name": "웰턴 캐리어", "brand": "brighton", "brand_name": "브라이튼 캐리어"}]


def test_parse_29cm_search_keeps_reviews_and_likes():
    rows = twentyninecm.parse_search({"data": [{"itemNo": 5, "itemName": "쿼디 캐리어", "frontBrandNo": 62659,
                                                "frontBrandNameKor": "리드볼트", "frontBrandNameEng": "LEADVAULT",
                                                "reviewCount": 334, "reviewAveragePoint": 5.0, "heartCount": 3068}]})
    assert rows[0] == {"id": "5", "name": "쿼디 캐리어", "brand": "62659", "brand_name": "리드볼트",
                       "brand_name_en": "LEADVAULT", "review_count": 334, "rating": 5.0, "likes": 3068,
                       "url": "https://www.29cm.co.kr/products/5"}


def test_map_categories_uses_synonyms_and_contained_labels():
    known = {"캐리어": "004009", "백팩": "004001", "브리프 케이스": "004008", "가방": "004000"}
    assert cr.map_categories(["러기지", "캐리어", "비즈니스 가방"], known) == [("캐리어", "004009"),
                                                                       ("브리프 케이스", "004008")]
    assert cr.map_categories(["데일리 백팩"], known) == [("백팩", "004001")]
    assert cr.map_categories(["반려동물 사료"], known) == []


def test_age_bands_follow_key_target():
    assert cr.age_bands(_brand()) == ["AGE_BAND_ALL"]
    t = Target(age_min=35, age_max=None, label="35+")
    assert cr.age_bands(_brand(target=t)) == ["AGE_BAND_ALL", "AGE_BAND_35", "AGE_BAND_40"]
    t = Target(age_min=18, age_max=29, label="Gen Z")
    assert cr.age_bands(_brand(target=t)) == ["AGE_BAND_ALL", "AGE_BAND_MINOR", "AGE_BAND_20", "AGE_BAND_25"]


def test_pick_brand_exact_name_first_then_prefix_in_category_search():
    rows = [{"brand": "brighten", "brand_name": "브라이튼"}] + \
           [{"brand": "brighton", "brand_name": "브라이튼 캐리어"}] * 5
    assert cr.pick_brand(rows, ["브라이튼"], prefix=True) == ("brighten", "브라이튼")  # 같은 이름이 있으면 그것
    cat_rows = [{"brand": "brighton", "brand_name": "브라이튼 캐리어"}] * 5
    assert cr.pick_brand(cat_rows, ["브라이튼"], prefix=True) == ("brighton", "브라이튼 캐리어")
    assert cr.pick_brand(cat_rows, ["브라이튼"], prefix=False) is None
    # 영문 별칭이 플랫폼 브랜드 코드와 같아도 맞춘다
    assert cr.pick_brand([{"brand": "samsonite", "brand_name": "쌤소나이트"}], ["Samsonite"], prefix=False) == \
        ("samsonite", "쌤소나이트")


def test_rank_facts_record_best_rank_and_zero_when_outside():
    ranking = [{"rank": 1, "id": "9", "name": "X", "brand": "brighton"},
               {"rank": 8, "id": "3", "name": "P", "brand": "samsonite"},
               {"rank": 20, "id": "4", "name": "Q", "brand": "samsonite"}]
    facts = cr.rank_facts(brand_id="SO", entity="샘소나이트", platform_brand="samsonite", ranking=ranking,
                          category=("캐리어", "004009"), band="AGE_BAND_35", measured_at=date(2026, 11, 13))
    by = {f.metric: f for f in facts}
    assert int(by["commerce_best_rank"].value) == 8 and by["commerce_best_rank"].unit == "rank"
    assert int(by["commerce_ranked_items"].value) == 2 and by["commerce_ranked_items"].dims["top_n"] == "3"
    none = cr.rank_facts(brand_id="SO", entity="코르딕스", platform_brand="cordix", ranking=ranking,
                         category=("캐리어", "004009"), band="AGE_BAND_ALL", measured_at=date(2026, 11, 13))
    assert [(f.metric, int(f.value)) for f in none] == [("commerce_ranked_items", 0)]  # '100위 밖'을 말할 근거


def test_sku_facts_pick_most_reviewed_product():
    goods = [{"id": "1", "name": "A", "review_count": 3, "url": "u1"},
             {"id": "2", "name": "B", "review_count": 40, "url": "u2"}]
    facts = cr.sku_facts(brand_id="SO", entity="샘소나이트", platform="musinsa", goods=goods, likes=388,
                         measured_at=date(2026, 11, 13))
    by = {f.metric: f for f in facts}
    assert int(by["commerce_top_reviews"].value) == 40 and by["commerce_top_reviews"].dims["product"] == "B"
    assert int(by["commerce_brand_reviews"].value) == 43 and int(by["commerce_top_likes"].value) == 388
    assert cr.sku_facts(brand_id="SO", entity="x", platform="29cm", goods=[], likes=None,
                        measured_at=date(2026, 11, 13)) == []
