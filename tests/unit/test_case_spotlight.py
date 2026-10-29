"""A person-featured case material gets its own deep-dive slide, and leaves the grid alone."""
from datetime import date

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from tests.quality_fixture import build_inputs


def test_featured_case_gets_spotlight_slide(tmp_path):
    project, facts, posts, materials = build_inputs(tmp_path / "assets")
    campaign = [m for m in materials if m.section_id == "campaign"]
    campaign[0].featured = True

    r = build_deck(BuildInputs(project=project, facts=facts, posts=posts, materials=materials,
                               omitted_slots={"3-1-B2": "검증 범위 외", "3-1-B3": "검증 범위 외"},
                               generated_on=date(2026, 10, 12)))
    qc = run_qc(r.deck, r.metrics.registry, lambda a: r.assets.get(a))
    assert qc.blocks == 0, [i for i in qc.issues if i.severity == "block"]

    spot = next(s for s in r.deck.slides if s.slide_id == "C1c-spot1")  # competitors' cases: C1c
    assert spot.template_id == "case_spotlight.v1"
    assert spot.asset_ids == [campaign[0].asset.id]

    grid_slides = [s for s in r.deck.slides if s.slide_id.startswith("C1c") and s.slide_id != "C1c-spot1"]
    grid_assets = {a for s in grid_slides for a in s.asset_ids}
    assert campaign[0].asset.id not in grid_assets
    assert sum(len(s.asset_ids) for s in grid_slides) == len(campaign) - 1
