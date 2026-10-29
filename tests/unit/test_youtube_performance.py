"""2-5 YouTube 채널 성과 (core/composition/owned.py)."""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.facts import Fact
from core.schemas.slidespec import LineChartBlock
from tests.helpers import load_fixture


def _fact(metric, value, brand_id="B1", entity="브랜드A", **dims):
    return Fact(id=f"F-{metric}-{dims}", content_hash="h", brand_id=brand_id, entity=entity, metric=metric,
               value=Decimal(str(value)), unit="count", dims={"channel": "youtube", **dims},
               period_start=date(2026, 1, 1), period_end=date(2026, 9, 30), measured_at=date(2026, 9, 30),
               source="ScrapeCreators", confidence="verified", verification_status="eligible")


def test_youtube_performance_renders_monthly_trend_and_caption():
    project, _, _ = load_fixture()
    facts = [
        _fact("owned_followers", 42000),
        _fact("owned_views_avg", 15000, format="video"),
        _fact("owned_views_avg", 48000, format="shorts"),
        _fact("owned_posts_by_month", 2, month="2026-07"),
        _fact("owned_posts_by_month", 0, month="2026-08"),
        _fact("owned_posts_by_month", 3, month="2026-09"),
    ]
    cfg = project.model_copy(update={"enabled_slides": ["2-5"]})
    result = build_deck(BuildInputs(project=cfg, facts=facts, generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "2-5")
    chart = next(b for b in slide.blocks if isinstance(b, LineChartBlock))
    assert [p.value for p in chart.series[0].points] == [2.0, 0.0, 3.0]

    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "2-5"]
    assert blocking == [], blocking


def test_youtube_performance_absent_without_data():
    project, _, _ = load_fixture()
    cfg = project.model_copy(update={"enabled_slides": ["2-5"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "2-5" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "2-5")
    assert slot.readiness == "needs_input"
