"""P5-2 진단 템플릿 6종: D1 진단 요약, D2 강점·약점 증명, D3 경쟁 구도, D4 CDJ, D5 활동 제안, D6 결론."""
from datetime import date
from decimal import Decimal

from pptx import Presentation

from app.services import diagnosis as planner
from core.composition import diagnosis as dt
from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.diagnosis import Diagnosis
from core.schemas.facts import Fact
from core.schemas.materials import ReviewSnapshotRef
from core.schemas.project import Brand
from core.schemas.slidespec import BarChartBlock, LineChartBlock, TableBlock, TextBlock
from tests.helpers import load_fixture
from tests.unit.test_diagnosis_planner import good_answer
from tests.unit.test_p3_chart_pages import DAY, _p3_facts, _voc

SELF = frozenset({"브랜드A", "브랜드B"})


def _review(i, entity, role, count, platform="musinsa", brand_id="B1"):
    return ReviewSnapshotRef(id=f"REV{i}", brand_id=brand_id, entity=entity, role=role, platform=platform,
                             product_name=f"{entity} 캐리어", product_url=f"https://example.com/p/{i}", rating=4.6,
                             review_count=count, measured_at=DAY, review_status="accepted")


REVIEWS = [_review(1, "브랜드A", "self", 1250), _review(2, "경쟁X", "competitor", 3400),
           _review(3, "경쟁Y", "competitor", 820), _review(4, "경쟁X", "competitor", 99999, platform="coupang")]


def _inputs(project=None, diagnosis=None, reviews=REVIEWS, slides=("cover", "index", "divider")):
    base, facts, posts = load_fixture()
    project = (project or base).model_copy(update={"enabled_slides": list(slides)})
    materials = [_voc("V1", "negative", title="바퀴 소리가 너무 커요"), _voc("V2", "positive", title="튼튼해서 오래 써요")]
    return BuildInputs(project=project, facts=[*facts.facts, *posts.facts, *_p3_facts()], posts=posts.posts,
                       materials=materials, reviews=list(reviews), generated_on=DAY, diagnosis=diagnosis or {})


def _diagnosis(inputs=None, brand_id="B1") -> dict:
    """A planner-checked diagnosis for the fixture (the same path a deck build takes)."""
    pi = planner.gather(inputs or _inputs(), brand_id)
    answer = good_answer(pi)
    months = [f["ref"] for f in pi.facts if f["metric"] == "shop_click_index" and f["entity"] == "캐리어"]
    answer["claims"][2]["chart"] = {"type": "line", "fact_refs": months}  # a real monthly series
    answer["cdj"].append({"stage": "인지", "touchpoint": "포털 검색", "state": "이름은 앎", "activity": "검색 광고"})
    data, _ = planner.clean(answer, pi)
    return data.model_dump(mode="json")


def _texts(slide) -> str:
    out = []
    for b in slide.blocks:
        if isinstance(b, TextBlock):
            out.append("".join(p.rendered() for para in b.paragraphs for p in para.parts))
        elif isinstance(b, TableBlock):
            out.append(" ".join("".join(x.rendered() for p in c.paragraphs for x in p.parts) for r in b.rows for c in r.cells))
    return " ".join(out)


def _blocks(result, ids=None):
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None, SELF)
    return [i for i in qc.issues if i.severity == "block" and (ids is None or i.slide_id in ids)]


def test_diagnosis_pages_build_bind_and_render(tmp_path):
    r = build_deck(_inputs(diagnosis={"B1": _diagnosis()}))
    pages = {s.slide_id: s for s in r.deck.slides}
    assert {"D1", "D2-c1", "D2-c2", "D2-c3", "D3", "D4", "D5", "D6"} <= set(pages)
    order = [s.slide_id for s in r.deck.slides]
    assert order.index("D1") < order.index("D2-c1") < order.index("D4") < order.index("D5") < order.index("D6")
    assert pages["D3"].chapter == "competitor" and pages["D1"].chapter == "summary"
    assert all(pages[k].template_id == dt.TEMPLATES[k.split("-")[0]] for k in pages if k.startswith("D"))
    assert not _blocks(r), _blocks(r)
    path = render_deck(r.deck, tmp_path / "diagnosis.pptx")
    assert len(Presentation(str(path)).slides) == len(r.deck.slides)


def test_d1_five_heads_numbers_and_brackets():
    r = build_deck(_inputs(diagnosis={"B1": _diagnosis()}))
    d1 = next(s for s in r.deck.slides if s.slide_id == "D1")
    heads = [b for b in d1.blocks if b.block_id.startswith("d1_head") and b.block_id.endswith("_t")]
    assert ["".join(p.text for p in h.paragraphs[0].parts) for h in heads] == ["인지", "고려", "탐색", "구매", "검증"]
    nums = [b for b in d1.blocks if b.block_id.startswith("d1_num")]
    assert nums and all(b.paragraphs[0].parts[0].type == "fact" for b in nums)
    assert {"강점 구간", "이탈 구간"} <= {_texts_of(b) for b in d1.blocks if b.block_id.endswith("_t") and "구간" in _texts_of(b)}
    assert "검색 인지는 앞서고" in _texts(d1)  # the one-line diagnosis is the lead
    cards = [b for b in d1.blocks if b.block_id.endswith("_title") and b.block_id.startswith("insight")]
    assert [_texts_of(b) for b in cards] == ["강점", "약점", "약점"]
    assert {b.fact_id for b in d1.bindings} >= {f.fact_id for f in Diagnosis.model_validate(_diagnosis()).funnel
                                                 if f.fact_id}


def _texts_of(block) -> str:
    return "".join(p.rendered() for para in block.paragraphs for p in para.parts)


def test_d2_headline_chart_quotes_and_hidden_numbers():
    data = _diagnosis()
    r = build_deck(_inputs(diagnosis={"B1": data}))
    pages = {s.slide_id: s for s in r.deck.slides}
    strength, noise, blog = pages["D2-c1"], pages["D2-c2"], pages["D2-c3"]
    claim = next(b for b in strength.blocks if b.block_id == "lead_claim")
    assert "선두" in _texts_of(claim) and any(b.block_id == "lead_evidence" for b in strength.blocks)
    assert isinstance(next(b for b in strength.blocks if b.block_id == "chart"), BarChartBlock)
    chart_head = next(b for b in strength.blocks if b.block_id == "chart_header")
    assert chart_head.paragraphs[0].parts[0].type == "name"  # labels with digits are metadata, not claims
    foot = next(b for b in strength.blocks if b.block_id == "footnote")
    assert any(part.type == "meta" and part.key == "source" for p in foot.paragraphs for part in p.parts)
    assert "튼튼해서 오래 써요" in _texts(strength)  # the cited consumer post as a card
    # the headline cites a number the chart does not draw: it sits under the chart (QC LEAD_CITES_HIDDEN)
    assert not any(b.block_id.startswith("ev") for b in noise.blocks)  # the chart already draws its numbers
    assert isinstance(next(b for b in blog.blocks if b.block_id == "chart"), LineChartBlock)
    assert len([b for b in blog.blocks if b.block_id.endswith("_value") and b.block_id.startswith("ev")]) == 2
    assert "바퀴 소리가 너무 커요" in _texts(noise)
    assert not _blocks(r, {"D2-c1", "D2-c2", "D2-c3"})
    # 빼기: an excluded claim has no page; a stale number drops the claim's page instead of drawing it
    data["claims"][1]["excluded"] = True
    data["claims"][0]["evidence"][0]["parts"][1]["fact_id"] = "F-gone"
    r = build_deck(_inputs(diagnosis={"B1": data}))
    ids = {s.slide_id for s in r.deck.slides}
    assert "D2-c2" not in ids and "D2-c1" not in ids and "D2-c3" in ids


def test_d3_review_gap_on_one_platform_or_price_tiers():
    r = build_deck(_inputs(diagnosis={"B1": _diagnosis()}))
    d3 = next(s for s in r.deck.slides if s.slide_id == "D3")
    chart = next(b for b in d3.blocks if isinstance(b, BarChartBlock))
    assert [it.entity for it in chart.items] == ["브랜드A", "경쟁X", "경쟁Y"]  # self first, one platform only
    assert "99,999" not in _texts(d3) and "무신사" in _texts(d3)
    price = [Fact(id=f"F-price-{e}", content_hash=e, brand_id="B1", entity=e, metric="official_price",
                  value=Decimal(v), unit="krw", period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                  measured_at=DAY, source="공식몰", confidence="verified", verification_status="eligible")
             for e, v in (("브랜드A", 389000), ("경쟁X", 259000), ("경쟁Y", 529000))]
    inputs = _inputs(diagnosis={"B1": _diagnosis()})
    inputs.facts += price
    d3 = next(s for s in build_deck(inputs).deck.slides if s.slide_id == "D3")
    table = next(b for b in d3.blocks if isinstance(b, TableBlock))
    assert [row.ref for row in table.rows] == ["경쟁Y", "브랜드A", "경쟁X"]  # high → low price
    assert [c.label for c in table.columns] == ["가격 계층", "브랜드", "공식몰 가격", "리뷰 수"]
    # no competitor numbers: no page (never an empty one)
    r = build_deck(_inputs(diagnosis={"B1": _diagnosis()}, reviews=REVIEWS[:1]))
    assert "D3" not in {s.slide_id for s in r.deck.slides}


def test_d4_cdj_table_and_d5_action_cards():
    r = build_deck(_inputs(diagnosis={"B1": _diagnosis()}))
    pages = {s.slide_id: s for s in r.deck.slides}
    table = next(b for b in pages["D4"].blocks if isinstance(b, TableBlock))
    assert [c.label for c in table.columns] == ["단계", "고객 접점", "인지 상태", "인지 증대 활동"]
    assert len(table.rows) == 3 and table.rows[0].cells[2].fill == "pale"  # 인지 상태 칩
    d5 = pages["D5"]
    heads = [_texts_of(b) for b in d5.blocks if b.block_id.startswith("d5_head") and b.block_id.endswith("_t")]
    assert heads == ["소셜", "콘텐츠"]  # only pillars with a proposal
    assert "탐색" in [_texts_of(b) for b in d5.blocks if b.block_id.endswith("_chip_t")]
    basis = [b for b in d5.blocks if b.block_id.endswith("_basis")]
    assert basis and all(any(p.type == "fact" for p in b.paragraphs[0].parts) for b in basis)
    assert not _blocks(r, {"D4", "D5"})


def test_d6_sets_self_brands_side_by_side_without_ranking():
    base, _, _ = load_fixture()
    b2 = Brand(id="B2", name="브랜드B", categories=["가방"], target=base.brands[0].target, competitors=["경쟁X"])
    project = base.model_copy(update={"brands": [base.brands[0], b2]})
    inputs = _inputs(project=project)
    d1 = _diagnosis(inputs, "B1")
    d2 = Diagnosis.model_validate(d1).model_copy(update={"profile": "다른 브랜드 진단"}).model_dump(mode="json")
    inputs.diagnosis = {"B1": d1, "B2": d2}
    r = build_deck(inputs)
    d6 = next(s for s in r.deck.slides if s.slide_id == "D6")
    assert d6.chapter == "summary"  # after every brand's own part
    table = next(b for b in d6.blocks if isinstance(b, TableBlock))
    assert [row.ref for row in table.rows] == ["B1", "B2"]  # project order, no score column
    assert [c.label for c in table.columns] == ["자사 브랜드", "끊긴 구간", "소셜", "인플루언서", "콘텐츠"]
    assert "검증" in _texts(d6) and not any(b.block_id == "chart" for b in d6.blocks)
    per_brand = [s.slide_id for s in r.deck.slides if s.slide_id.startswith("D1")]
    assert per_brand == ["D1-B1", "D1-B2"]
    assert not _blocks(r, {"D6", "D1-B1", "D1-B2"})  # no self brand comparison anywhere


def test_no_diagnosis_no_pages_and_builder_skips_ai_headlines():
    r = build_deck(_inputs())
    assert not [s for s in r.deck.slides if s.template_id in dt.OWN_HEADLINE]
    assert not [p for p in r.deck.plan if p.template_id.startswith("D")]
    assert dt.OWN_INSIGHTS < dt.OWN_HEADLINE and dt.TEMPLATES["D2"] not in dt.OWN_INSIGHTS


def test_stored_ai_writing_never_replaces_the_diagnosis_headline():
    from core.composition.build import body_fingerprint
    inputs = _inputs(diagnosis={"B1": _diagnosis()})
    pages = {s.slide_id: s for s in build_deck(inputs).deck.slides}
    head = {"claim": [{"parts": [{"type": "text", "text": "다른 AI 헤드라인"}]}], "evidence": []}
    cards = {"insights": [{"title": {"parts": [{"type": "text", "text": "AI 카드"}]},
                           "body_segments": {"parts": [{"type": "text", "text": "AI 카드 설명"}]}}]}
    inputs.ai_writing = {"lead": {k: {"fp": body_fingerprint(pages[k]), **head} for k in ("D1", "D2-c1")},
                         "insights": {k: {"fp": body_fingerprint(pages[k]), **cards} for k in ("D1", "D2-c1")}}
    pages = {s.slide_id: s for s in build_deck(inputs).deck.slides}
    assert "다른 AI 헤드라인" not in _texts(pages["D1"]) + _texts(pages["D2-c1"])
    assert "AI 카드" not in _texts(pages["D1"]) and "AI 카드" in _texts(pages["D2-c1"])  # D2 takes page insights


def test_diagnosis_profile_reorders_story_and_moves_raw_pages_to_appendix(tmp_path):
    base, _, _ = load_fixture()
    project = base.model_copy(update={
        "report_profile": "diagnosis",
        "enabled_slides": ["cover", "index", "divider", "1-1", "2-1", "OW-CMP", "2-8a", "3-1", "5-1", "A-source"],
    })
    inputs = _inputs(project=project, diagnosis={"B1": _diagnosis()}, slides=project.enabled_slides)
    result = build_deck(inputs)
    ids = [slide.slide_id for slide in result.deck.slides]

    assert ids[:2] == ["cover", "index"]
    assert ids.index("D1") < ids.index("D2-c1") < ids.index("D3") < ids.index("3-1-B1")
    assert ids.index("3-1-B1") < ids.index("D4") < ids.index("D5") < ids.index("D6")
    assert ids.index("D6") < ids.index("2-8a")

    d1 = next(slide for slide in result.deck.slides if slide.slide_id == "D1")
    raw = next(slide for slide in result.deck.slides if slide.slide_id == "2-8a")
    assert d1.chapter == "diagnosis:B1"
    assert raw.chapter == "appendix" and raw.page_role == "appendix"
    related = raw.block("related_page")
    assert "관련 본문" in related.paragraphs[0].plain() and "p." in related.paragraphs[0].plain()
    assert not _blocks(result), _blocks(result)
    path = render_deck(result.deck, tmp_path / "diagnosis-profile.pptx")
    assert len(Presentation(str(path)).slides) == len(result.deck.slides)


def test_new_project_schema_defaults_to_diagnosis_but_legacy_loader_keeps_diagnostic():
    from core.schemas.project import Project, load_project

    raw = {
        "name": "새 프로젝트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"]}],
        "enabled_slides": ["cover"],
    }
    assert Project.model_validate(raw).report_profile == "diagnosis"
    assert load_project(raw).report_profile == "diagnostic"
