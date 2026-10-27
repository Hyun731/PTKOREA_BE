"""Search 2-8a's consolidated ①②③ insights: real Findings, not fabricated narrative."""
from datetime import date

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.slidespec import TextBlock
from tests.helpers import load_fixture


def _build():
    project, facts, posts = load_fixture()
    return build_deck(BuildInputs(project=project, facts=facts.facts + posts.facts, posts=posts.posts,
                                  generated_on=date(2026, 10, 12)))


def test_search_share_insight_bullet_matches_its_finding():
    r = _build()
    slide = next(s for s in r.deck.slides if s.slide_id == "2-8a")
    r04 = [f for f in r.findings if f.rule_id == "RULE-R04"]
    assert r04, "fixture must produce at least one RULE-R04 finding for this test to be meaningful"

    insights = next((b for b in slide.blocks if isinstance(b, TextBlock) and b.block_id == "insights"), None)
    assert insights is not None, "expected room for the insights block in this single-brand fixture"
    assert [p.bullet for p in insights.paragraphs] == ["①"]
    assert r04[0].summary["rival"] in insights.paragraphs[0].plain()
    assert insights.region.h > 0

    qc = run_qc(r.deck, r.metrics.registry, lambda a: r.assets.get(a))
    assert not [i for i in qc.issues if i.severity == "block"], qc.issues


def test_search_share_insight_facts_only_cite_what_is_shown():
    r = _build()
    slide = next(s for s in r.deck.slides if s.slide_id == "2-8a")
    insights = next(b for b in slide.blocks if isinstance(b, TextBlock) and b.block_id == "insights")
    cited = {part.fact_id for p in insights.paragraphs for part in p.parts if part.type == "fact"}
    shown = {part.fact_id for b in slide.blocks if isinstance(b, TextBlock) and b.block_id != "insights"
            for p in b.paragraphs for part in p.parts if part.type == "fact"}
    assert cited <= shown


def test_combo_and_target_slides_also_get_insights():
    r = _build()
    combo = next(s for s in r.deck.slides if s.slide_id.startswith("2-8c"))
    target = next(s for s in r.deck.slides if s.slide_id == "2-8d")
    for slide in (combo, target):
        insights = next((b for b in slide.blocks if isinstance(b, TextBlock) and b.block_id == "insights"), None)
        assert insights is not None, f"expected an insights block on {slide.slide_id}"
        assert insights.paragraphs[0].bullet == "①"

    qc = run_qc(r.deck, r.metrics.registry, lambda a: r.assets.get(a))
    assert not [i for i in qc.issues if i.severity == "block"], qc.issues
