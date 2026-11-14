from pathlib import Path
import shutil

import pytest

from core.golden_baseline import GoldenBaselineError, load_golden_baseline

FIXTURE = Path(__file__).parents[1] / "fixtures" / "golden_baseline"


def test_loads_complete_synthetic_baseline():
    baseline = load_golden_baseline(FIXTURE, strict=True)
    assert baseline.manifest.baseline_id == "synthetic-luggage-2026-v1"
    assert len(baseline.slides) == 4
    assert len(baseline.facts) == 3
    assert baseline.claims[-1].fact_ids == ["F-AWARE-001", "F-GAP-001"]


def test_rejects_claim_reference_to_missing_fact(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    claims = (target / "claims.csv").read_text()
    (target / "claims.csv").write_text(claims.replace("F-AWARE-001;F-GAP-001", "F-AWARE-001;F-MISSING"))
    with pytest.raises(GoldenBaselineError, match="F-MISSING"):
        load_golden_baseline(target)


def test_strict_rejects_records_needing_review(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    facts = (target / "facts.csv").read_text()
    (target / "facts.csv").write_text(facts.replace("source_checked", "needs_review", 1))
    load_golden_baseline(target)
    with pytest.raises(GoldenBaselineError, match="needs_review"):
        load_golden_baseline(target, strict=True)


def test_rejects_incomplete_slide_map(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    lines = (target / "slides.csv").read_text().splitlines()
    (target / "slides.csv").write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(GoldenBaselineError, match="missing pages"):
        load_golden_baseline(target)


def test_rejects_fact_on_another_brand_slide(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    facts = (target / "facts.csv").read_text()
    (target / "facts.csv").write_text(facts.replace("Brand Alpha,2,market_growth", "Brand Beta,2,market_growth"))
    with pytest.raises(GoldenBaselineError, match="brand does not match"):
        load_golden_baseline(target)


def test_rejects_derived_fact_without_calculation(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    facts = (target / "facts.csv").read_text()
    (target / "facts.csv").write_text(facts.replace("Synthetic calculation,derived,,60 - 48", "Synthetic calculation,derived,,"))
    with pytest.raises(GoldenBaselineError, match="derived facts require calculation"):
        load_golden_baseline(target)


def test_strict_rejects_empty_fact_and_claim_ledgers(tmp_path):
    target = tmp_path / "baseline"
    shutil.copytree(FIXTURE, target)
    for name in ("facts.csv", "claims.csv"):
        path = target / name
        path.write_text(path.read_text().splitlines()[0] + "\n")
    load_golden_baseline(target)
    with pytest.raises(GoldenBaselineError, match="has no records"):
        load_golden_baseline(target, strict=True)
