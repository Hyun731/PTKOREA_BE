from pathlib import Path

import pytest

from core.golden_baseline import load_golden_baseline
from core.golden_inputs import build_golden_input_plan
from core.schemas.project import Project


FIXTURE = Path(__file__).parents[1] / "fixtures" / "golden_baseline"


def _project() -> Project:
    return Project.model_validate({
        "name": "Synthetic import target",
        "client": "Synthetic client",
        "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [
            {"id": "B1", "name": "Alpha Local", "categories": ["Luggage"], "competitors": ["Rival A"]},
            {"id": "B2", "name": "Beta Local", "competitors": ["Rival B"]},
            {"id": "B3", "name": "Gamma Local", "competitors": ["Rival C"]},
        ],
        "enabled_slides": ["cover"],
    })


def _plan():
    return build_golden_input_plan(
        load_golden_baseline(FIXTURE, strict=True),
        _project(),
        "PRJ-synthetic",
        {"Brand Alpha": "B1", "Brand Beta": "B2", "Brand Gamma": "B3"},
    )


def test_builds_materials_claims_and_compatible_facts():
    plan = _plan()
    assert plan.summary() == {
        "baseline_id": "synthetic-luggage-2026-v1",
        "project_id": "PRJ-synthetic",
        "brands": {"Brand Alpha": "B1", "Brand Beta": "B2", "Brand Gamma": "B3"},
        "materials": 3,
        "facts": 2,
        "claims": 3,
        "accepted_claims": 2,
        "pending_claims": 1,
        "unsupported_facts": 1,
        "unsupported_by_reason": {"unsupported unit pp": 1},
    }
    assert {fact.metric for fact in plan.facts} == {"percent"}
    assert {material.section_id for material in plan.materials} == {"market", "campaign"}
    conclusion = next(claim for claim in plan.claims if claim.baseline_claim_id == "C-CONCLUSION-001")
    assert conclusion.fact_ids == [next(f.fact_id for f in plan.facts if f.baseline_fact_id == "F-AWARE-001")]
    assert conclusion.unsupported_fact_ids == ["F-GAP-001"]
    assert conclusion.review_status == "pending"


def test_generated_ids_are_deterministic_and_database_safe():
    first, second = _plan(), _plan()
    assert first.model_dump() == second.model_dump()
    assert all(len(item.fact_id) <= 40 and item.fact_id.startswith("F-") for item in first.facts)
    assert all(len(item.material_id) <= 40 for item in first.materials)


def test_requires_explicit_one_to_one_brand_mapping():
    baseline = load_golden_baseline(FIXTURE, strict=True)
    with pytest.raises(ValueError, match="missing brand mappings"):
        build_golden_input_plan(baseline, _project(), "PRJ-x", {"Brand Alpha": "B1"})
    with pytest.raises(ValueError, match="different project brand"):
        build_golden_input_plan(baseline, _project(), "PRJ-x", {
            "Brand Alpha": "B1", "Brand Beta": "B1", "Brand Gamma": "B3",
        })
