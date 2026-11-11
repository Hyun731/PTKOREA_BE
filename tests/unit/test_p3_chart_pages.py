"""P3-3 search, demand, and consumer chart pages."""
from datetime import date
from decimal import Decimal

from pptx import Presentation

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.facts import Fact
from core.schemas.materials import CaseMaterial, SourceRef
from core.schemas.slidespec import BarChartBlock, LineChartBlock
from tests.helpers import load_fixture

DAY = date(2026, 10, 12)
P3_SLIDES = ["MN1", "BL1", "VC1", "PP1", "SH1"]


def _fact(metric, value, entity="브랜드A", **dims):
    suffix = "-".join(f"{key}-{value}" for key, value in sorted(dims.items()))
    return Fact(
        id=f"F-{metric}-{entity}-{suffix}", content_hash="h", brand_id="B1", entity=entity, metric=metric,
        value=Decimal(str(value)), unit="count", dims={key: str(value) for key, value in dims.items()},
        period_start=date(2026, 1, 1), period_end=date(2026, 9, 30), measured_at=DAY,
        source="synthetic_fixture", confidence="verified", verification_status="eligible",
    )


def _voc(identifier, sentiment, *, title=None):
    return CaseMaterial(
        id=identifier, brand_id="B1", entity="브랜드A", section_id="voc", title=title or f"{identifier} 원문",
        source=SourceRef(id=f"SRC-{identifier}", title=f"{identifier} 원문", url=f"https://example.com/{identifier}",
                         publisher="커뮤니티", published_at=DAY),
        review_status="accepted", voc_sentiment=sentiment, voc_topic="quality", voc_awareness="search",
    )


def _project(slides=P3_SLIDES):
    project, _, _ = load_fixture()
    return project.model_copy(update={"enabled_slides": slides})


def _build(project, facts=(), materials=()):
    return build_deck(BuildInputs(project=project, facts=list(facts), materials=list(materials), generated_on=DAY))


def _p3_facts():
    facts = [
        _fact("mention_total", 1200, channel="blog", keyword_group="brand", keyword="브랜드A"),
        _fact("mention_total", 900, channel="cafe", keyword_group="brand", keyword="브랜드A"),
        _fact("mention_total", 1800, "경쟁X", channel="blog", keyword_group="brand", keyword="경쟁X"),
        _fact("mention_total", 1300, "경쟁X", channel="cafe", keyword_group="brand", keyword="경쟁X"),
        _fact("blog_type_share", 65, type="real_use", keyword="브랜드A", n=30),
        _fact("blog_type_share", 35, type="sponsored", keyword="브랜드A", n=30),
        _fact("blog_type_share", 45, "경쟁X", type="real_use", keyword="경쟁X", n=30),
        _fact("blog_type_share", 55, "경쟁X", type="sponsored", keyword="경쟁X", n=30),
        _fact("voc_negative_rate", 32, site="전체", n=40),
        _fact("voc_negative_rate", 45, site="카페", n=20),
        _fact("voc_negative_rate", 20, site="블로그", n=20),
        _fact("pain_point_count", 18, pain_point="바퀴 소음", n=40),
        _fact("pain_point_count", 12, pain_point="손잡이 불편", n=40),
        _fact("pain_point_count", 9, pain_point="가격", n=40),
    ]
    for keyword, values in {"캐리어": [70, 80, 100, 90], "여행가방": [45, 50, 72, 95]}.items():
        for month, value in zip(("2026-01", "2026-02", "2026-03", "2026-04"), values):
            facts.append(_fact("shop_click_index", value, keyword, month=month, scale_id="shopping-2026"))
    facts += [
        _fact("shop_peak_lift", 30, "캐리어", month="2026-03"),
        _fact("shop_peak_lift", 25, "여행가방", month="2026-04"),
        _fact("shop_click_share", 42, "캐리어", by="age", group="20"),
        _fact("shop_click_share", 35, "캐리어", by="age", group="30"),
        _fact("shop_click_share", 38, "여행가방", by="age", group="30"),
        _fact("shop_click_share", 31, "여행가방", by="age", group="40"),
    ]
    return facts


def test_p3_chart_pages_build_bind_and_render(tmp_path):
    materials = [_voc("V1", "negative"), _voc("V2", "negative"), _voc("V3", "positive"), _voc("V4", "neutral")]
    result = _build(_project(), _p3_facts(), materials)
    pages = {slide.slide_id: slide for slide in result.deck.slides}
    assert set(pages) == set(P3_SLIDES)
    assert pages["MN1"].chapter == "competitor"
    assert pages["BL1"].chapter == pages["VC1"].chapter == pages["PP1"].chapter == "customer"
    assert pages["SH1"].chapter == "competitor"
    assert all(slide.bindings for slide in pages.values())
    assert all(slide.needs_review and slide.is_data for slide in pages.values())
    assert any(isinstance(block, BarChartBlock) and block.multi for block in pages["MN1"].blocks)
    assert any(isinstance(block, BarChartBlock) and block.stacked for block in pages["BL1"].blocks)
    assert any(isinstance(block, LineChartBlock) for block in pages["SH1"].blocks)
    qc = run_qc(result.deck, result.metrics.registry, lambda asset: None)
    assert not [issue for issue in qc.issues if issue.severity == "block" and issue.slide_id in pages], qc.issues

    path = render_deck(result.deck, tmp_path / "p3-3.pptx")
    presentation = Presentation(str(path))
    assert len(presentation.slides) == len(P3_SLIDES)
    assert any(shape.name == "line" and shape.has_chart for shape in presentation.slides[-1].shapes)


def test_p3_chart_pages_leave_needs_input_slots_when_data_is_thin():
    result = _build(_project(), [_fact("mention_total", 100, channel="blog", keyword_group="brand")])
    assert not result.deck.slides
    slots = {slot.slot_id: slot for slot in result.deck.plan}
    assert set(slots) == set(P3_SLIDES)
    assert all(slot.readiness == "needs_input" and slot.reason for slot in slots.values())
