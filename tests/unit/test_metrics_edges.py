"""Calculation edge cases (PRD 15 A01~A04, DEVELOPMENT_PLAN 8.1)."""
import json
from decimal import Decimal

from core.composition.formatters import fmt_lead_count, fmt_pp, fmt_share
from core.ingestion.acceptance import accept_batch
from core.ingestion.csv_import import import_facts_csv, import_posts_csv
from core.metrics.engine import competition_ranks, compute
from core.rules.engine import run_rules
from core.schemas.project import load_project
from tests.helpers import FIXTURES, load_fixture

HEADER = "brand,entity,metric,value,unit,dims,period,measured_at,source,url,method,confidence\n"
POST_HEADER = "post_id,brand,channel,creator,owner_type,posted_at,measured_at,followers,followers_measured_at,views,likes,comments,likes_hidden,product,url\n"


def project():
    return load_project(json.loads((FIXTURES / "project.json").read_text(encoding="utf-8")))


def row(entity, value, window="9M", seg="all", scale="s1", cat=None, period="2026-01-01~2026-09-30",
        measured="2026-10-01", source="t", confidence="verified", metric="search_group_sum", month=None):
    if metric == "search_group_sum":
        dims = {"window": window, "seg": seg, "scale_id": scale}
        if cat:
            dims["cat"] = cat
    else:
        dims = {"month": month, "seg": seg, "scale_id": scale}
    d = json.dumps(dims, ensure_ascii=False).replace('"', '""')
    return f'B1,{entity},{metric},{value},index,"{d}",{period},{measured},{source},,,{confidence}\n'


def run(csv_text, posts_text=None):
    p = project()
    facts = accept_batch(import_facts_csv(csv_text, p, "b"))
    posts = accept_batch(import_posts_csv(posts_text or POST_HEADER, p, "p"))
    m = compute(p, facts.facts + posts.facts, posts.posts)
    return p, facts, m, run_rules(p, m)


# A01 ----------------------------------------------------------------------

def test_a01_name_and_cat_rows_do_not_mix_denominators():
    _, metrics, _ = __import__("tests.helpers", fromlist=["run_fixture"]).run_fixture()
    name = metrics.find_share("B1", "9M", "all")
    cat = metrics.find_share("B1", "9M", "all", "캐리어")
    assert name.total == Decimal(700) and cat.total == Decimal(1000)
    assert name.formula == "share" and cat.formula == "share_combo"


def test_mixed_scale_ids_never_combine():
    text = HEADER + row("브랜드A", 10, scale="s1") + row("경쟁X", 10, scale="s1") + row("경쟁Y", 10, scale="s2")
    _, _, m, _ = run(text)
    assert m.find_share("B1", "9M", "all") is None
    assert {i.code for i in m.issues} == {"INCOMPLETE_SET"}


# A02 ----------------------------------------------------------------------

def test_a02_missing_entity_blocks_share():
    text = HEADER + row("브랜드A", 10) + row("경쟁X", 10)
    _, _, m, _ = run(text)
    assert m.find_share("B1", "9M", "all") is None
    assert m.issues[0].code == "INCOMPLETE_SET" and m.issues[0].detail["missing"] == ["경쟁Y"]


def _monthly(values_a, values_x, skip_month=None):
    text = HEADER
    for i, (a, x) in enumerate(zip(values_a, values_x), start=1):
        month = f"2026-{i:02d}"
        if month == skip_month:
            text += row("브랜드A", a, metric="search_index_monthly", month=month, scale="m")
            continue
        text += row("브랜드A", a, metric="search_index_monthly", month=month, scale="m")
        text += row("경쟁X", x, metric="search_index_monthly", month=month, scale="m")
    return text


def test_a02_missing_month_breaks_r03_run():
    # X leads in months 2,3 and 5,6 but month 4 is missing for X: two runs of 2, not 4.
    a = [50, 50, 50, 50, 50, 50]
    x = [40, 60, 60, 60, 60, 60]
    _, _, _, findings = run(_monthly(a, x, skip_month="2026-04"))
    r03 = [f for f in findings if f.rule_id == "RULE-R03"]
    assert len(r03) == 1
    assert r03[0].summary["months"] == 2
    assert r03[0].summary["start_month"] == "2026-05"  # equal length -> most recent


def test_r03_tie_breaks_run():
    a = [50, 50, 50, 50]
    x = [60, 50, 60, 40]
    _, _, _, findings = run(_monthly(a, x))
    assert not [f for f in findings if f.rule_id == "RULE-R03"]


# A03 ----------------------------------------------------------------------

def test_a03_lower_self_catching_up_is_not_lead_shrinking():
    # Self is behind X in both windows and closing the gap: R04 must not fire.
    text = HEADER
    text += row("브랜드A", 300, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("경쟁X", 500, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("경쟁Y", 200, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("브랜드A", 380, scale="m") + row("경쟁X", 420, scale="m") + row("경쟁Y", 200, scale="m")
    _, _, _, findings = run(text)
    r04 = [f for f in findings if f.rule_id == "RULE-R04"]
    # Y is the only rival below self at 12M (gap 10pp) and the gap grows -> no finding.
    assert r04 == []


def test_r04_reversal_excluded():
    text = HEADER
    text += row("브랜드A", 400, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("경쟁X", 360, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("경쟁Y", 240, window="12M", period="2025-10-01~2026-09-30", scale="l")
    text += row("브랜드A", 300, scale="m") + row("경쟁X", 320, scale="m") + row("경쟁Y", 200, scale="m")
    _, _, _, findings = run(text)
    assert not [f for f in findings if f.rule_id == "RULE-R04"]


# A04 ----------------------------------------------------------------------

def test_a04_hidden_likes_missing_comments_zero_denominator():
    posts = POST_HEADER
    posts += "H,B1,instagram,c1,creator,2026-05-01,2026-10-01,1000,2026-10-01,,,10,true,,\n"   # hidden likes
    posts += "C,B1,instagram,c2,creator,2026-05-02,2026-10-01,1000,2026-10-01,,50,,false,,\n"  # comments null
    posts += "Z,B1,youtube,c3,creator,2026-05-03,2026-10-01,0,2026-10-01,0,0,0,false,,\n"     # zero denominators
    _, _, m, findings = run(HEADER, posts)
    pm = {p.post.post_id: p for p in m.posts["B1"]}
    assert pm["H"].er.partial is True and pm["H"].er.value == Decimal(1)
    assert pm["H"].like_view is None and pm["H"].ad_heuristic.value == "unknown"
    assert pm["C"].er is None  # missing comments is never 0
    assert pm["Z"].er is None and pm["Z"].like_view is None
    # views sum 0 -> no ad share
    assert m.ad["B1"].ad_view_share is None
    assert not [f for f in findings if f.rule_id == "RULE-R10"]


def test_r10_needs_two_view_posts_and_coverage():
    posts = POST_HEADER + "A,B1,youtube,c,creator,2026-05-01,2026-10-01,100,2026-10-01,1000000,10,1,false,,\n"
    _, _, m, findings = run(HEADER, posts)
    assert m.ad["B1"].ad_view_share.value == Decimal(100)
    assert not [f for f in findings if f.rule_id == "RULE-R10"]


def test_posts_outside_period_are_excluded_from_ad_share():
    posts = POST_HEADER
    posts += "A,B1,youtube,c,creator,2025-05-01,2026-10-01,100,2026-10-01,1000,10,1,false,,\n"
    posts += "B,B1,youtube,c,creator,2026-05-01,2026-10-01,100,2026-10-01,1000,100,1,false,,\n"
    _, _, m, _ = run(HEADER, posts)
    assert m.ad["B1"].view_eligible_posts.value == 1


# Ingestion ----------------------------------------------------------------

def test_window_label_must_match_dates():
    text = HEADER + row("브랜드A", 1, window="12M", period="2026-01-01~2026-09-30")
    res = import_facts_csv(text, project(), "b")
    assert res.errors[0].code == "WINDOW_MISMATCH"


def test_rejects_nan_negative_unknown_metric_and_benchmark_entity():
    text = HEADER + row("브랜드A", "NaN") + row("브랜드A", -1) + row("벤치마크Z", 1)
    text += row("브랜드A", 1).replace("search_group_sum", "shop_kw_rank")
    res = import_facts_csv(text, project(), "b")
    assert [e.code for e in res.errors] == ["INVALID_VALUE", "INVALID_VALUE", "UNKNOWN_ENTITY", "UNKNOWN_METRIC"]
    assert res.facts == []


def test_duplicate_natural_key_latest_measured_wins():
    text = HEADER + row("브랜드A", 1, measured="2026-10-01") + row("브랜드A", 2, measured="2026-10-02") + row("브랜드A", 3, measured="2026-10-01")
    res = import_facts_csv(text, project(), "b")
    assert len(res.facts) == 1 and res.facts[0].value == Decimal(2)
    assert len(res.duplicates) == 2


def test_provider_conflict_is_held():
    text = HEADER + row("브랜드A", 1, source="naver") + row("브랜드A", 2, source="csv")
    text += row("경쟁X", 1) + row("경쟁Y", 1)
    _, facts, m, _ = run(text)
    assert all(f.conflict_key for f in facts.facts if f.entity == "브랜드A")
    assert m.find_share("B1", "9M", "all") is None
    assert "SOURCE_CONFLICT" in {i.code for i in m.issues}


def test_fact_id_independent_of_row_order():
    a = HEADER + row("브랜드A", "100.0000000000") + row("경쟁X", 1)
    b = HEADER + row("경쟁X", 1) + row("브랜드A", 100)
    ids_a = {f.id for f in import_facts_csv(a, project(), "b").facts}
    ids_b = {f.id for f in import_facts_csv(b, project(), "b").facts}
    assert ids_a == ids_b


def test_unaccepted_batch_is_not_used():
    p, facts, posts = load_fixture(accept=False)
    m = compute(p, facts.facts + posts.facts, posts.posts)
    assert m.share_tables == [] and m.posts["B1"] == []


def test_estimated_parent_propagates():
    text = HEADER + row("브랜드A", 1, confidence="estimated") + row("경쟁X", 1) + row("경쟁Y", 2)
    _, _, m, _ = run(text)
    t = m.find_share("B1", "9M", "all")
    assert all(s.confidence == "estimated" for s in t.shares.values())


def test_competition_ranks_ties():
    assert competition_ranks({"a": Decimal(5), "b": Decimal(5), "c": Decimal(1)}) == {"a": 1, "b": 1, "c": 3}


def test_formatter_rounding_boundaries():
    assert fmt_share(Decimal("16.85")) == "16.9%"
    assert fmt_share(Decimal("16.849999999")) == "16.8%"
    assert fmt_pp(Decimal("-9.19")) == "−9.2pp" and fmt_pp(Decimal("0.04")) == "0.0pp"
    assert fmt_lead_count(1000000) == "100만" and fmt_lead_count(594925) == "59.5만" and fmt_lead_count(9999) == "9,999"


def test_project_rules():
    import pytest
    base = json.loads((FIXTURES / "project.json").read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(base))
    bad["brands"].append({**base["brands"][0], "id": "B2", "name": "브랜드B", "competitors": ["브랜드A"]})
    with pytest.raises(ValueError, match="다른 자사 브랜드"):
        load_project(bad)
    dup = json.loads(json.dumps(base))
    dup["brands"][0]["keyword_groups"][1]["keywords"].append("브랜드A")
    with pytest.raises(ValueError, match="중복"):
        load_project(dup)
    p = load_project(base)
    assert p.report_profile == "diagnostic" and "report_profile" in p.import_defaults_applied
    assert {w.section_id for w in p.section_windows} == {"search", "influencer"}
