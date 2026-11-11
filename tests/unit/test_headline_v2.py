"""P3-4 헤드라인 v2: 주장 + 근거 두 줄 — 규칙 검사, 이전 저장 형식 호환, 덱에 반영, QC."""
from datetime import date

from core.composition.build import BuildInputs, body_fingerprint, build_deck, fingerprint, lead_of
from core.composition.chrome import PartFactory
from core.quality.qc import run_qc, self_brands_in
from core.schemas.slidespec import Headline, Paragraph, Part, TextBlock
from tests.helpers import load_fixture


def _inputs(**kw) -> BuildInputs:
    p, f, po = load_fixture()
    return BuildInputs(project=p, facts=f.facts + po.facts, posts=po.posts, generated_on=date(2026, 10, 12), **kw)


def _share_fact(result) -> str:
    slide = next(s for s in result.deck.slides if s.slide_id == "2-8a")
    return next(b.fact_id for b in slide.bindings if not b.block_id.startswith("lead"))


def T(text):
    return Part(type="text", text=text)


def F(fid="F-1", display="61.0%"):
    return Part(type="fact", fact_id=fid, formatter="share", display=display)


def test_self_brand_names_in_free_text_match_longest_first():
    assert self_brands_in("샘소나이트 레드는 샘소나이트보다", ["샘소나이트", "샘소나이트 레드"]) == {"샘소나이트", "샘소나이트 레드"}
    assert self_brands_in("샘소나이트 레드 인지 우위", ["샘소나이트", "샘소나이트 레드"]) == {"샘소나이트 레드"}


def test_old_claim_only_override_still_reads_and_new_one_draws_two_tiers():
    r = build_deck(_inputs())
    fid = _share_fact(r)
    pf = PartFactory(r.metrics.registry)
    old = [Paragraph(parts=[T("사람이 고친 헤드라인")])]  # saved before P3-4
    r1 = build_deck(_inputs(lead_overrides={"2-8a": old}))
    s1 = next(s for s in r1.deck.slides if s.slide_id == "2-8a")
    assert lead_of(s1).block_id == "lead_claim" and lead_of(s1).paragraphs[0].plain() == "사람이 고친 헤드라인"
    assert not any(isinstance(b, TextBlock) and b.role == "lead_evidence" for b in s1.blocks)
    assert Headline.coerce([{"parts": [{"type": "text", "text": "x"}]}]).claim[0].plain() == "x"

    new = Headline(claim=[Paragraph(parts=[T("검색 점유 "), Part(type="text", text="우위 축소", color="accent")])],
                   evidence=[Paragraph(parts=[T("자사 점유 "), pf.fact(fid, "share")])])
    r2 = build_deck(_inputs(lead_overrides={"2-8a": new}))
    s2 = next(s for s in r2.deck.slides if s.slide_id == "2-8a")
    ev = next(b for b in s2.blocks if isinstance(b, TextBlock) and b.role == "lead_evidence")
    claim = lead_of(s2)
    assert ev.block_id == "lead_evidence" and ev.paragraphs[0].bullet == "-" and ev.region.y > claim.region.y
    assert claim.max_lines == 1 and claim.region.y + claim.region.h <= ev.region.y
    assert any(b.block_id == "lead_evidence" for b in s2.bindings)
    qc = run_qc(r2.deck, r2.metrics.registry, lambda a: None)
    assert not [i for i in qc.issues if i.slide_id == "2-8a" and i.severity == "block"]
    assert not [i for i in qc.issues if i.slide_id == "2-8a" and i.code == "LEAD_NO_EVIDENCE"]


def test_ai_headline_is_used_only_while_the_body_is_unchanged():
    r = build_deck(_inputs())
    slide = next(s for s in r.deck.slides if s.slide_id == "2-8a")
    fid = _share_fact(r)
    head = {"claim": [{"parts": [{"type": "text", "text": "AI 주장"}]}],
            "evidence": [{"parts": [{"type": "text", "text": "점유 "}, {"type": "fact", "fact_id": fid, "formatter": "share"}]}]}
    fresh = {"lead": {"2-8a": {"fp": body_fingerprint(slide), **head}}}
    stale = {"lead": {"2-8a": {"fp": "old", **head}}}
    hit = next(s for s in build_deck(_inputs(ai_writing=fresh)).deck.slides if s.slide_id == "2-8a")
    miss = next(s for s in build_deck(_inputs(ai_writing=stale)).deck.slides if s.slide_id == "2-8a")
    assert lead_of(hit).paragraphs[0].plain() == "AI 주장" and any(b.role == "lead_evidence" for b in hit.blocks
                                                                    if isinstance(b, TextBlock))
    assert lead_of(miss).paragraphs[0].plain() == lead_of(slide).paragraphs[0].plain()
    # a person's headline wins over the AI one
    person = build_deck(_inputs(ai_writing=fresh, lead_overrides={"2-8a": [Paragraph(parts=[T("사람 문장")])]}))
    assert lead_of(next(s for s in person.deck.slides if s.slide_id == "2-8a")).paragraphs[0].plain() == "사람 문장"
    # the fingerprint ignores the headline itself, so applying it does not invalidate it
    assert body_fingerprint(hit) == body_fingerprint(slide)
    # an empty ai_writing keeps the deck fingerprint of decks built before P3-4
    assert fingerprint(_inputs()) == fingerprint(_inputs(ai_writing={}))


def test_qc_warns_on_a_body_page_without_evidence_and_blocks_three_numbers_per_line():
    r = build_deck(_inputs())
    qc = run_qc(r.deck, r.metrics.registry, lambda a: None)
    assert any(i.code == "LEAD_NO_EVIDENCE" and i.severity == "warn" for i in qc.issues)
    fid = _share_fact(r)
    pf = PartFactory(r.metrics.registry)
    f = pf.fact(fid, "share")
    bad = Headline(claim=[Paragraph(parts=[T("주장")])], evidence=[Paragraph(parts=[T("a "), f, T(" b "), f, T(" c "), f])])
    r2 = build_deck(_inputs(lead_overrides={"2-8a": bad}))
    qc2 = run_qc(r2.deck, r2.metrics.registry, lambda a: None)
    assert any(i.code == "LEAD_TOO_MANY_NUMBERS" and i.slide_id == "2-8a" for i in qc2.issues)
