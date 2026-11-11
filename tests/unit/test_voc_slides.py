"""5-1 소비자 인식 원문 · 5-2 브랜드 인식 경로 (core/composition/customer.py)."""
from datetime import date

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.materials import CaseMaterial, SourceRef
from tests.helpers import load_fixture


def _voc(id_, sentiment, topic, awareness, *, entity="브랜드A", sponsored=False, day="2026-05-01",
        headline="테스트 요약", status="accepted"):
    return CaseMaterial(id=id_, brand_id="B1", entity=entity, section_id="voc", title=f"글 {id_}", event_name=headline,
                        source=SourceRef(id=f"SRC-{id_}", title=f"글 {id_}", url=f"https://blog.naver.com/x/{id_}",
                                        publisher="네이버 블로그", published_at=date.fromisoformat(day)),
                        review_status=status, voc_sentiment=sentiment, voc_topic=topic, voc_awareness=awareness,
                        voc_sponsored=sponsored)


def test_voc_summary_renders_quotes_by_sentiment_and_top_complaints():
    project, _, _ = load_fixture()
    materials = [
        _voc("1", "positive", "price", "referral"),
        _voc("2", "negative", "shipping", "other"),
        _voc("3", "negative", "shipping", "other"),
        _voc("4", "negative", "price", "other"),
    ] + [_voc(str(i), "positive", "quality", "search") for i in range(5, 21)]
    cfg = project.model_copy(update={"enabled_slides": ["5-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "5-1")
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "5-1"]
    assert blocking == [], blocking
    assert slide.source_ids and len(slide.source_ids) == 8


def test_voc_summary_absent_without_classified_materials():
    project, _, _ = load_fixture()
    cfg = project.model_copy(update={"enabled_slides": ["5-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=[], generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "5-1" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "5-1")
    assert slot.readiness == "needs_input"


def test_voc_summary_excludes_sponsored_and_candidate_materials():
    project, _, _ = load_fixture()
    materials = [
        _voc("1", "positive", "price", "referral", sponsored=True),  # 협찬 — 제외
        _voc("2", "positive", "quality", "search", status="candidate"),  # 채택 전 — 제외
    ]
    cfg = project.model_copy(update={"enabled_slides": ["5-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "5-1" for s in result.deck.slides)


def test_awareness_channel_page_ranks_by_share():
    project, _, _ = load_fixture()
    materials = [
        _voc("1", "positive", "price", "referral"),
        _voc("2", "neutral", "quality", "referral"),
        _voc("3", "negative", "design", "search"),
    ] + [_voc(str(i), "positive", "quality", "referral") for i in range(4, 21)]
    cfg = project.model_copy(update={"enabled_slides": ["5-2"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "5-2")
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "5-2"]
    assert blocking == [], blocking
    assert len(slide.source_ids) == 20


def test_voc_pages_with_fewer_than_twenty_sources_are_thin():
    project, _, _ = load_fixture()
    materials = [_voc(str(i), "negative", "shipping", "other") for i in range(1, 20)]
    cfg = project.model_copy(update={"enabled_slides": ["5-1", "5-2"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    assert not {"5-1", "5-2"} & {slide.slide_id for slide in result.deck.slides}
    slots = {slot.slot_id: slot for slot in result.deck.plan}
    assert slots["5-1"].readiness == slots["5-2"].readiness == "thin"
    assert result.deck.counts()["thin"] == 2


def test_a_competitor_s_voc_never_fills_the_self_brand_s_slide():
    """Phase 1-3 collects self + competitor VOC, but 5-1/5-2 show only the self brand's own voice."""
    project, _, _ = load_fixture()
    materials = [_voc("1", "positive", "price", "referral", entity="경쟁X")]
    cfg = project.model_copy(update={"enabled_slides": ["5-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "5-1" for s in result.deck.slides)
