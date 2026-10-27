"""Golden regression against quantitative_samples/expected.json (PRD 15)."""
from decimal import Decimal

from core.composition.formatters import fmt_er, fmt_share, fmt_strength
from core.decimalx import ser, ser_strength
from tests.helpers import load_fixture, run_fixture

SHARE_KEYS = {
    "12M_all": ("12M", "all", None),
    "9M_all": ("9M", "all", None),
    "9M_T": ("9M", "T", None),
    "9M_all_cat_캐리어": ("9M", "all", "캐리어"),
}


def test_input_counts(expected):
    _, facts, posts = load_fixture()
    assert not facts.errors and not posts.errors
    assert len(facts.facts) == expected["input_counts"]["facts"]
    assert len(posts.posts) == expected["input_counts"]["posts"]


def test_shares(expected):
    _, metrics, _ = run_fixture()
    for key, (window, seg, cat) in SHARE_KEYS.items():
        table = metrics.find_share("B1", window, seg, cat)
        assert table is not None, key
        for entity, exp in expected["shares"][key].items():
            value = table.share(entity)
            assert ser(value) == exp["value"], (key, entity)
            assert fmt_share(value) == exp["display"], (key, entity)


def test_posts(expected):
    _, metrics, _ = run_fixture()
    by_id = {pm.post.post_id: pm for pm in metrics.posts["B1"]}
    for post_id, exp in expected["posts"].items():
        pm = by_id[post_id]
        assert ser(pm.er.value) == exp["er"], post_id
        assert fmt_er(pm.er.value, pm.er.partial) == exp["er_display"], post_id
        assert (ser(pm.like_view.value) if pm.like_view else None) == exp["like_view"], post_id
        assert pm.ad_heuristic.value == exp["ad_heuristic"], post_id


def test_ad_view_share(expected):
    _, metrics, _ = run_fixture()
    ad = metrics.ad["B1"]
    assert ser(ad.ad_view_share.value) == expected["ad_view_share"]["value"]
    assert fmt_share(ad.ad_view_share.value) == expected["ad_view_share"]["display"]
    assert ser(ad.coverage.value) == expected["ad_view_share"]["classification_coverage"]


def _ser_summary(summary: dict) -> dict:
    return {k: ser(v) if isinstance(v, Decimal) else v for k, v in summary.items()}


def test_findings(expected):
    _, _, findings = run_fixture()
    assert len(findings) == expected["finding_count"]
    for got, exp in zip(findings, expected["findings"]):
        assert got.rule_id == exp["rule_id"]
        assert got.brand_id == exp["brand_id"]
        assert ser_strength(got.strength) == exp["strength"], got.rule_id
        assert fmt_strength(got.strength) == exp["strength_display"], got.rule_id
        assert _ser_summary(got.summary) == exp["summary"], got.rule_id


def test_deterministic_ids():
    """Same normalized input -> same IDs regardless of run."""
    _, m1, f1 = run_fixture()
    _, m2, f2 = run_fixture()
    assert set(m1.registry.derived) == set(m2.registry.derived)
    assert [f.fact_ids for f in f1] == [f.fact_ids for f in f2]
