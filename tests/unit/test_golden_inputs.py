from pathlib import Path
from decimal import Decimal

import pytest

from core.golden_baseline import load_golden_baseline
from core.golden_baseline import BaselineFact
from core.golden_inputs import _metric_for, _number_candidates, build_golden_input_plan
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
        "facts": 3,
        "claims": 3,
        "accepted_claims": 3,
        "pending_claims": 0,
        "unsupported_facts": 0,
        "unsupported_by_reason": {},
    }
    assert {fact.metric for fact in plan.facts} == {"percent", "percentage_point"}
    assert {material.section_id for material in plan.materials} == {"market", "campaign"}
    conclusion = next(claim for claim in plan.claims if claim.baseline_claim_id == "C-CONCLUSION-001")
    assert conclusion.fact_ids == [
        next(f.fact_id for f in plan.facts if f.baseline_fact_id == baseline_id)
        for baseline_id in ("F-AWARE-001", "F-GAP-001")
    ]
    assert conclusion.unsupported_fact_ids == []
    assert conclusion.review_status == "accepted"


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


@pytest.mark.parametrize(("unit", "metric"), [
    ("usd", "amount_usd"),
    ("score", "score"),
    ("years", "duration_years"),
    ("group", "group_count"),
    ("ratio", "ratio"),
    ("days", "duration_days"),
    ("months", "duration_months"),
    ("pp", "percentage_point"),
])
def test_supports_report_units_without_coercion(unit, metric):
    fact = BaselineFact(
        baseline_id="synthetic-luggage-2026-v1", fact_id="F-UNIT", brand="Brand Alpha", slide_page=2,
        metric="source_metric", value=Decimal("2"), unit=unit, period_start="2026-01-01",
        period_end="2026-01-31", measured_on="2026-02-01", source_name="Synthetic source",
        source_type="customer_provided", evidence_page=2, verification="source_checked",
    )
    assert _metric_for(fact) == (metric, None)
    assert any(candidate.startswith("2") for candidate in _number_candidates(fact))
