"""2-2 운영 공백 분석 (core/composition/owned.py)."""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.facts import Fact
from core.schemas.slidespec import LineChartBlock
from tests.helpers import load_fixture


def _monthly_fact(month, count, brand_id="B1", entity="브랜드A"):
    return Fact(id=f"F-{month}", content_hash="h", brand_id=brand_id, entity=entity, metric="owned_posts_by_month",
               value=Decimal(count), unit="count", dims={"channel": "instagram", "month": month},
               period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), measured_at=date(2026, 3, 31),
               source="ScrapeCreators", confidence="verified", verification_status="eligible")


def test_operating_gap_shows_brand_with_zero_month():
    project, _, _ = load_fixture()
    facts = [_monthly_fact("2026-01", 3), _monthly_fact("2026-02", 0), _monthly_fact("2026-03", 2)]
    cfg = project.model_copy(update={"enabled_slides": ["2-2"]})
    result = build_deck(BuildInputs(project=cfg, facts=facts, materials=[], generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "2-2")
    chart = next(b for b in slide.blocks if isinstance(b, LineChartBlock))
    assert [p.value for p in chart.series[0].points] == [3.0, 0.0, 2.0]

    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "2-2"]
    assert blocking == [], blocking


def test_operating_gap_absent_when_no_zero_month():
    project, _, _ = load_fixture()
    facts = [_monthly_fact("2026-01", 3), _monthly_fact("2026-02", 1), _monthly_fact("2026-03", 2)]
    cfg = project.model_copy(update={"enabled_slides": ["2-2"]})
    result = build_deck(BuildInputs(project=cfg, facts=facts, materials=[], generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "2-2" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "2-2")
    assert slot.readiness == "needs_input"
