"""P3-1 OW-CMP 자사 vs 경쟁사 채널 비교 (core/composition/compare.py, owned.channel_compare_page)."""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.facts import Fact
from core.schemas.materials import CommentSentiment, OwnedPostRef
from core.schemas.slidespec import BarChartBlock, TextBlock
from tests.helpers import load_fixture

GEN = date(2026, 10, 12)


def _fact(metric, value, channel, entity="브랜드A", brand_id="B1", status="eligible", **dims):
    return Fact(id=f"F-{brand_id}-{entity}-{metric}-{channel}-{sorted(dims.items())}", content_hash="h", brand_id=brand_id,
                entity=entity, metric=metric, value=Decimal(str(value)), unit="count", dims={"channel": channel, **dims},
                period_start=date(2026, 1, 1), period_end=date(2026, 9, 30), measured_at=date(2026, 9, 30),
                source="ScrapeCreators Instagram", confidence="verified", verification_status=status)


def _owned(entity, followers, posts, likes, channel="instagram", **kw):
    return [_fact("owned_followers", followers, channel, entity, **kw),
            _fact("owned_posts_monthly", posts, channel, entity, **kw),
            _fact("owned_likes_median", likes, channel, entity, **kw)]


def _project(slides=("OW-CMP",)):
    project, _, _ = load_fixture()
    return project.model_copy(update={"enabled_slides": list(slides)})


def _build(project, facts, owned_posts=()):
    return build_deck(BuildInputs(project=project, facts=facts, materials=[], owned_posts=list(owned_posts),
                                  generated_on=GEN))


def _pages(result):
    return [s for s in result.deck.slides if s.slide_id.startswith("OW-CMP")]


def _qc_blocks(result, prefix="OW-CMP"):
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    return [i for i in qc.issues if i.severity == "block" and (i.slide_id or "").startswith(prefix)]


def test_self_and_competitor_bars_per_channel_with_bindings_and_clean_qc():
    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 19116, "13.22", 136),
             *_owned("경쟁Y", 9418, "3.11", 17),
             _fact("owned_followers", 9500, "youtube", "브랜드A"), _fact("owned_followers", 12000, "youtube", "경쟁X"),
             _fact("owned_videos_monthly", "0.0", "youtube", "브랜드A", format="video"),
             _fact("owned_videos_monthly", "1.11", "youtube", "브랜드A", format="shorts"),
             _fact("owned_videos_monthly", "2.5", "youtube", "경쟁X", format="video"),
             _fact("owned_views_avg", 1332038, "youtube", "브랜드A", format="shorts"),
             _fact("owned_views_avg", 4000, "youtube", "경쟁X", format="shorts"),
             _fact("owned_views_avg", 9000, "youtube", "경쟁X", format="video")]
    result = _build(_project(), facts)
    pages = _pages(result)
    assert len(pages) == 1
    page = pages[0]
    charts = [b for b in page.blocks if isinstance(b, BarChartBlock)]
    ig = {b.block_id: b for b in charts if b.block_id.startswith("row0_")}
    assert set(ig) == {"row0_followers", "row0_posts", "row0_engagement"}
    followers = ig["row0_followers"]
    assert [it.entity for it in followers.items] == ["브랜드A", "경쟁X", "경쟁Y"]
    assert [it.role for it in followers.items] == ["self", "key", "other"]  # key = 경쟁사 중 가장 높은 곳
    assert followers.items[0].display == "10,461"
    # YouTube: 월 게시 수 = 동영상 + 쇼츠(파생값), 조회는 한 형식(쇼츠)만 — 섞지 않는다
    yt_posts = next(b for b in charts if b.block_id == "row1_posts")
    assert [it.display for it in yt_posts.items] == ["1.1", "2.5"]
    yt_views = next(b for b in charts if b.block_id == "row1_views")
    assert [it.display for it in yt_views.items] == ["1,332,038", "4,000"]
    label = next(b for b in page.blocks if b.block_id == "row1_label")
    assert "쇼츠 기준" in "".join(p.plain() for p in label.paragraphs)
    # every bar is bound to its fact
    bound = {bd.fact_id for bd in page.bindings}
    assert all(it.fact_id in bound for b in charts for it in b.bar_items())
    assert _qc_blocks(result) == []
    # numbered insights at the bottom (shape names insight*)
    assert any(b.block_id == "insight0_title" for b in page.blocks)
    assert page.chapter == "company"


def test_channel_without_competitor_numbers_is_left_out_and_no_page_without_any():
    facts = [*_owned("브랜드A", 10461, "7.78", 224), _fact("owned_followers", 9500, "youtube", "브랜드A"),
             *_owned("경쟁X", 19116, "13.22", 136)]
    page = _pages(_build(_project(), facts))[0]
    assert not any(b.block_id.startswith("row1_") for b in page.blocks)  # YouTube: 경쟁사 수치 없음 → 줄 생략
    only_self = [*_owned("브랜드A", 10461, "7.78", 224)]
    result = _build(_project(), only_self)
    assert _pages(result) == []
    slot = next(p for p in result.deck.plan if p.template_id == "OW-CMP")
    assert slot.readiness == "needs_input"


def test_candidate_facts_never_reach_the_page():
    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 19116, "13.22", 136, status="candidate")]
    assert _pages(_build(_project(), facts)) == []


def test_follows_2_1_and_sits_right_after_it():
    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 19116, "13.22", 136),
             _fact("owned_followers", 9500, "youtube", "브랜드A")]
    result = _build(_project(("2-1",)), facts)
    ids = [s.slide_id for s in result.deck.slides]
    assert ids.index("OW-CMP") == ids.index("2-1") + 1


def test_more_than_four_channels_continue_on_the_next_page():
    facts = []
    for ch in ("instagram", "youtube", "tiktok", "facebook", "threads"):
        facts += [_fact("owned_followers", 1000, ch, "브랜드A"), _fact("owned_followers", 2000, ch, "경쟁X")]
    pages = _pages(_build(_project(), facts))
    assert [p.slide_id for p in pages] == ["OW-CMP", "OW-CMP-p2"]
    assert pages[1].parent_slide_id == "OW-CMP"
    assert sum(1 for b in pages[0].blocks if b.block_id.endswith("_label") and b.block_id.startswith("row")) == 4


def test_comment_sentiment_is_a_stacked_bar_with_sample_note():
    def post(i, entity, pos, neg, neu):
        return OwnedPostRef(id=f"P{entity}{i}", brand_id="B1", entity=entity, channel="instagram", url="https://x",
                            comment_sentiment=CommentSentiment(positive=pos, negative=neg, neutral=neu,
                                                               sample_size=pos + neg + neu))
    posts = [post(i, e, 6, 2, 2) for e in ("브랜드A", "경쟁X") for i in range(3)]
    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 19116, "13.22", 136)]
    result = _build(_project(), facts, posts)
    page = _pages(result)[0]
    sent = next(b for b in page.blocks if b.block_id == "row0_sentiment")
    assert sent.stacked and [s.name for s in sent.series] == ["긍정", "중립", "부정"]
    assert sent.categories == ["브랜드A", "경쟁X"]
    assert sent.series[0].items[0].display == "60.0%"
    foot = next(b for b in page.blocks if isinstance(b, TextBlock) and b.role == "footnote")
    assert "n=30 · AI 분류" in foot.paragraphs[0].plain()
    assert _qc_blocks(result) == []


def test_one_page_per_self_brand_never_two_self_brands_together():
    project, _, _ = load_fixture()
    b1 = project.brands[0]
    b2 = b1.model_copy(update={"id": "B2", "name": "브랜드B", "competitors": ["경쟁Z", "브랜드A"]})
    proj = project.model_copy(update={"brands": [b1, b2], "enabled_slides": ["OW-CMP"]})
    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 19116, "13.22", 136),
             *_owned("브랜드B", 5000, "2", 50, brand_id="B2"), *_owned("경쟁Z", 7000, "3", 70, brand_id="B2"),
             *_owned("브랜드A", 10461, "7.78", 224, brand_id="B2")]
    result = _build(proj, facts)
    pages = _pages(result)
    assert [p.slide_id for p in pages] == ["OW-CMP-B1", "OW-CMP-B2"]
    for page, own in zip(pages, ("브랜드A", "브랜드B")):
        shown = {it.entity for b in page.blocks if isinstance(b, BarChartBlock) for it in b.bar_items()}
        assert own in shown and not ({"브랜드A", "브랜드B"} - {own}) & shown
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None, frozenset({"브랜드A", "브랜드B"}))
    assert not [i for i in qc.issues if i.code == "SELF_BRAND_COMPARISON"]


def test_rendered_kpi_charts_keep_value_labels_on_one_line_and_readable(tmp_path):
    from pptx import Presentation
    from pptx.oxml.ns import qn

    from core.rendering.pptx_renderer import render_deck

    facts = [*_owned("브랜드A", 10461, "7.78", 224), *_owned("경쟁X", 35210, "13.22", 136),
             *_owned("경쟁Y", 9418, "3.11", 17)]
    result = _build(_project(), facts)
    out = render_deck(result.deck, tmp_path / "d.pptx")
    slide = Presentation(out).slides[0]
    chart = next(sh for sh in slide.shapes if sh.name == "row0_followers").chart
    ser = chart.plots[0].series[0]._element
    assert all(bp.get("wrap") == "none" for bp in ser.iter(qn("a:bodyPr")))
    pos = {int(d.find(qn("c:idx")).get("val")): d.find(qn("c:dLblPos")).get("val") for d in ser.iter(qn("c:dLbl"))}
    assert 2 in pos  # 경쟁Y: pale bar → its own label (dark text), not white on light gray
    assert '"만"' in chart.plots[0].series[0].data_labels.number_format


def test_a_bar_narrower_than_its_label_puts_the_label_outside():
    from core.rendering.pptx_renderer import _label_width, _plot_width
    from core.schemas.slidespec import BarItem, Region

    items = [BarItem(entity=e, label=e, fact_id=e, display=d, value=v)
             for e, d, v in (("브랜드A", "10,461", 10461), ("내셔널지오그래픽", "35,210", 35210))]
    narrow = BarChartBlock(block_id="c", region=Region(x=0, y=0, w=190, h=80), items=items)
    ratio = 10461 / (35210 * 1.12)
    assert ratio > 0.22  # the old rule alone would have kept it inside
    assert ratio * _plot_width(narrow) < _label_width("10,461", 10.5)
