"""P1-2 파생 수치 (core/metrics/derived.py): 원문·댓글·리뷰 → 브랜드 단위 Fact."""
from datetime import date, datetime
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.metrics.derived import DerivedInputs, derive, footnote_label, measured_on, site_of
from core.schemas.materials import CaseMaterial, CommentSentiment, OwnedPostRef, ReviewSnapshotRef, SourceRef
from tests.helpers import load_fixture

PROJECT, _, _ = load_fixture()
DAY = date(2026, 10, 1)


def _voc(i: int, sentiment: str, *, url: str = "https://theqoo.net/1", topic: str = "price", path=None,
         status: str = "accepted", sponsored: bool = False, entity: str = "브랜드A") -> CaseMaterial:
    return CaseMaterial(id=f"M{i:03d}-{url[-6:]}", brand_id="B1", entity=entity, section_id="voc", title=f"원문 {i}",
                        source=SourceRef(id=f"S{i}", title="t", url=url, fetched_at=datetime(2026, 9, 20, 10)),
                        review_status=status, voc_sentiment=sentiment, voc_topic=topic, voc_awareness=path,
                        voc_sponsored=sponsored)


def _inputs(materials=(), posts=(), reviews=(), min_n=20) -> DerivedInputs:
    return DerivedInputs(project=PROJECT, materials=list(materials), owned_posts=list(posts), reviews=list(reviews),
                         measured_at=DAY, min_n=min_n)


def _by(facts, metric, **dims):
    return [f for f in facts if f.metric == metric and all(f.dims.get(k) == str(v) for k, v in dims.items())]


def test_negative_rate_by_site_and_overall():
    rows = [_voc(i, "negative" if i < 5 else "positive") for i in range(20)]  # 더쿠 20건 중 부정 5
    rows += [_voc(100 + i, "negative", url="https://www.clien.net/x") for i in range(20)]  # 클리앙 20건 모두 부정
    facts = derive(_inputs(rows))
    theqoo = _by(facts, "voc_negative_rate", site="더쿠")[0]
    assert theqoo.value == Decimal("25.0") and theqoo.dims["n"] == "20" and theqoo.unit == "percent"
    assert _by(facts, "voc_negative_rate", site="클리앙")[0].value == Decimal("100.0")
    overall = _by(facts, "voc_negative_rate", site="전체")[0]
    assert overall.value == Decimal("62.5") and overall.dims["n"] == "40"
    assert overall.verification_status == "eligible" and overall.usable
    assert overall.source == "derived" and "부정" in overall.method
    assert footnote_label(overall) == "n=40 · AI 분류"


def test_small_samples_make_no_rate():
    facts = derive(_inputs([_voc(i, "negative") for i in range(19)]))
    assert not _by(facts, "voc_negative_rate")
    assert _by(derive(_inputs([_voc(i, "negative") for i in range(19)], min_n=10)), "voc_negative_rate")


def test_only_accepted_non_sponsored_voc_counts():
    rows = [_voc(i, "positive") for i in range(20)]
    rows += [_voc(50 + i, "negative", status="candidate") for i in range(10)]
    rows += [_voc(80 + i, "negative", sponsored=True) for i in range(10)]
    fact = _by(derive(_inputs(rows)), "voc_negative_rate", site="전체")[0]
    assert fact.value == Decimal("0.0") and fact.dims["n"] == "20"


def test_topic_and_path_shares():
    rows = [_voc(i, "negative", topic="price" if i < 12 else "design", path="search" if i < 8 else None) for i in range(24)]
    rows += [_voc(100 + i, "positive", url="https://x.com/a", path="influencer") for i in range(12)]
    facts = derive(_inputs(rows))
    topics = {f.dims["topic"]: f.value for f in _by(facts, "voc_topic_share")}
    assert topics == {"price": Decimal("66.7"), "design": Decimal("33.3")}  # 가격 12+12, 디자인 12 (36건)
    paths = {f.dims["path"]: f.value for f in _by(facts, "voc_path_share")}
    assert paths == {"search": Decimal("40.0"), "influencer": Decimal("60.0")}  # 경로가 드러난 20건 기준
    assert _by(facts, "voc_path_share")[0].dims["n"] == "20"


def test_comment_sentiment_sums_posts_per_channel():
    posts = [OwnedPostRef(id=f"P{i}", brand_id="B1", entity="브랜드A", channel="instagram",
                          comment_sentiment=CommentSentiment(positive=6, negative=2, neutral=2, sample_size=10))
             for i in range(3)]
    posts.append(OwnedPostRef(id="PX", brand_id="B1", entity="브랜드A", channel="youtube",
                              comment_sentiment=CommentSentiment(positive=1, sample_size=1)))
    facts = derive(_inputs(posts=posts))
    ig = {f.dims["polarity"]: f.value for f in _by(facts, "comment_sentiment_rate", channel="instagram")}
    assert ig == {"positive": Decimal("60.0"), "negative": Decimal("20.0"), "neutral": Decimal("20.0")}
    assert not _by(facts, "comment_sentiment_rate", channel="youtube")  # n=1 < 20


def test_review_count_and_rating_scaled_to_five():
    def snap(i, rating, scale, status="accepted", access="ok"):
        return ReviewSnapshotRef(id=f"R{i}", brand_id="B1", entity="경쟁X", role="competitor", platform="무신사",
                                 product_name=f"상품{i}", product_url=f"https://m/{i}", rating=rating, rating_scale=scale,
                                 review_count=354, measured_at=date(2026, 9, 30), review_status=status, access_status=access)
    facts = derive(_inputs(reviews=[snap(1, 4.8, 5), snap(2, 9.0, 10), snap(3, 4.0, 5, status="candidate"),
                                    snap(4, 4.0, 5, access="unavailable")]))
    ratings = {f.dims["product"]: f.value for f in _by(facts, "review_rating")}
    assert ratings == {"상품1": Decimal("4.80"), "상품2": Decimal("4.50")}
    assert [f.value for f in _by(facts, "review_count")] == [Decimal(354), Decimal(354)]
    assert footnote_label(_by(facts, "review_count")[0]) is None  # a measurement, not an AI-classified share


def test_ids_are_stable_for_the_same_input():
    rows = [_voc(i, "negative") for i in range(20)]
    assert [f.id for f in derive(_inputs(rows))] == [f.id for f in derive(_inputs(list(reversed(rows))))]


def test_site_names_and_measured_date():
    assert site_of(_voc(1, "negative", url="https://m.blog.naver.com/abc")) == "네이버 블로그"
    assert site_of(_voc(1, "negative", url="https://gall.dcinside.com/x")) == "디시인사이드"
    assert measured_on(PROJECT, [_voc(1, "negative")], []) == date(2026, 9, 20)
    assert measured_on(PROJECT, [], []) == PROJECT.period.end


def test_build_deck_registers_derived_facts():
    project, f, po = load_fixture()
    voc = [_voc(i, "negative" if i % 4 == 0 else "positive") for i in range(20)]
    result = build_deck(BuildInputs(project=project, facts=f.facts + po.facts, posts=po.posts, materials=voc,
                                    generated_on=date(2026, 10, 12)))
    derived = [f for f in result.metrics.registry.facts.values() if f.source == "derived"]
    assert {f.metric for f in derived} >= {"voc_negative_rate", "voc_topic_share"}
    assert _by(derived, "voc_negative_rate", site="전체")[0].value == Decimal("25.0")
