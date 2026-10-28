"""2-1 채널 인벤토리 (core/composition/owned.py)."""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.facts import Fact
from core.schemas.slidespec import TableBlock
from tests.helpers import load_fixture


def _fact(metric, value, channel, brand_id="B1", entity="브랜드A", **dims):
    return Fact(id=f"F-{metric}-{channel}-{dims}", content_hash="h", brand_id=brand_id, entity=entity, metric=metric,
               value=Decimal(str(value)), unit="count", dims={"channel": channel, **dims},
               period_start=date(2026, 1, 1), period_end=date(2026, 9, 30), measured_at=date(2026, 9, 30),
               source="ScrapeCreators", confidence="verified", verification_status="eligible")


def test_channel_inventory_renders_from_owned_facts():
    project, _, _ = load_fixture()
    facts = [
        _fact("owned_followers", 125000, "instagram"),
        _fact("owned_posts_monthly", "8.5", "instagram"),
        _fact("owned_likes_median", 340, "instagram"),
        _fact("owned_followers", 42000, "youtube"),
        _fact("owned_videos_monthly", "2.3", "youtube", format="video"),
        _fact("owned_videos_monthly", "5.1", "youtube", format="shorts"),
        _fact("owned_views_avg", 15000, "youtube", format="video"),
        _fact("owned_views_avg", 48000, "youtube", format="shorts"),
    ]
    cfg = project.model_copy(update={"enabled_slides": ["2-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=facts, materials=[], generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "2-1")
    table = next(b for b in slide.blocks if isinstance(b, TableBlock))
    assert len(table.rows) == 1

    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "2-1"]
    assert blocking == [], blocking


def test_channel_inventory_absent_without_owned_facts():
    project, _, _ = load_fixture()
    cfg = project.model_copy(update={"enabled_slides": ["2-1"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=[], generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "2-1" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "2-1")
    assert slot.readiness == "needs_input"
