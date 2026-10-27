"""RULE-R11/R12/R13: the three post-based Finding rules added on top of R03-R06/R10.

Fixture posts_rules.csv (tests/fixtures/quantitative_samples/) carries three independent
groups so each rule can be asserted without the others interfering:
- R11: 3 high-ER/low-follower creators vs. 3 high-view/high-follower creators.
- R12: a creator with 3 "creator"-owned posts (median likes 1000) plus a "co" post (likes
  500, ratio 0.5 < 0.8).
- R13: two "self" posts 195 days apart (>= the 60-day threshold).
"""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from tests.helpers import load_fixture, run_fixture


def test_r11_er_top_has_smaller_audience():
    _, _, findings = run_fixture("posts_rules.csv")
    r11 = [f for f in findings if f.rule_id == "RULE-R11"]
    assert len(r11) == 1
    s = r11[0].summary
    assert s["er_top_median_followers"] == Decimal("10000")
    assert s["view_top_median_followers"] == Decimal("500000")


def test_r12_cocreator_underperforms():
    _, _, findings = run_fixture("posts_rules.csv")
    r12 = [f for f in findings if f.rule_id == "RULE-R12"]
    assert len(r12) == 1
    assert r12[0].summary["median_ratio"] == Decimal("0.5")


def test_r13_self_posting_gap():
    _, _, findings = run_fixture("posts_rules.csv")
    r13 = [f for f in findings if f.rule_id == "RULE-R13"]
    assert len(r13) == 1
    assert r13[0].summary["gap_days"] >= 60
    assert r13[0].summary["start"] == "2026-02-01"
    assert r13[0].summary["end"] == "2026-08-15"


def test_findings_are_fact_traced():
    _, metrics, findings = run_fixture("posts_rules.csv")
    new_rules = {f.rule_id: f for f in findings if f.rule_id in ("RULE-R11", "RULE-R12", "RULE-R13")}
    assert set(new_rules) == {"RULE-R11", "RULE-R12", "RULE-R13"}
    for f in new_rules.values():
        assert f.fact_ids
        for fid in f.fact_ids:
            assert metrics.registry.get(fid) is not None


def test_r11_leads_31_with_zero_qc_blocks():
    """R11 is the only competitor for the 3-1 lead on this fixture (R10 doesn't qualify) — it
    must actually win the slide, and its citation must not trip LEAD_CITES_HIDDEN/TOO_MANY."""
    p, f, po = load_fixture("posts_rules.csv")
    result = build_deck(BuildInputs(project=p, facts=f.facts + po.facts, posts=po.posts, generated_on=date(2026, 10, 1)))
    slide = next(s for s in result.deck.slides if s.slide_id == "3-1-B1")
    r11 = next(fn for fn in result.findings if fn.rule_id == "RULE-R11")
    assert slide.finding_ids == [r11.id]
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    assert qc.blocks == 0, [i for i in qc.issues if i.severity == "block"]


def test_r12_r13_surface_on_recap_with_zero_qc_blocks():
    """R12/R13 have no dedicated slide (spec only names Recap for R13) — both must still show
    up on 5-recap, and their derived-fact citations must not trip any QC check there."""
    p, f, po = load_fixture("posts_rules.csv")
    result = build_deck(BuildInputs(project=p, facts=f.facts + po.facts, posts=po.posts, generated_on=date(2026, 10, 1)))
    recap = next(s for s in result.deck.slides if s.slide_id == "5-recap")
    r12 = next(fn for fn in result.findings if fn.rule_id == "RULE-R12")
    r13 = next(fn for fn in result.findings if fn.rule_id == "RULE-R13")
    # Recap caps each pillar at its 2 strongest findings; R10 doesn't fire on this fixture
    # (see test_r11_leads_31...), so R12/R13 are the only two in "콘텐츠·관측 성과" and both fit.
    assert set(recap.finding_ids) >= {r12.id, r13.id}
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    assert qc.blocks == 0, [i for i in qc.issues if i.severity == "block"]
