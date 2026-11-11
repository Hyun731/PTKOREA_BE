"""P3-8 사례 상세(C2) 정리: 중복 요약 숨기기, 수치 없으면 이미지 넓히기, 하단 번호 인사이트, 외국어 원문 요약."""
from datetime import date
from pathlib import Path

from PIL import Image

from core.composition.build import BuildInputs, build_deck
from core.composition.cases import DETAIL_BODY_BOTTOM, is_foreign
from core.ingestion.manual import make_manual_fact
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.materials import AssetRef, CaseMaterial, ClaimRef, SourceRef
from core.schemas.slidespec import ImageBlock, Part, ShapeBlock, TextBlock
from tests.helpers import load_fixture

DAY = date(2026, 10, 12)
EN_QUOTE = ("Samsonite unveiled a limited capsule collection with a Seoul street-wear label, sold through "
            "pop-up stores in Seongsu and the brand's online flagship.")


def _case(tmp: Path, cid: str, *, metric: bool = False, implication: str = None, english: bool = False):
    img = tmp / f"{cid}.png"
    Image.new("RGB", (1280, 720), (90, 120, 160)).save(img)
    src = SourceRef(id=f"SRC-{cid}", title=f"{cid} 기사", url=f"https://example.com/{cid}", publisher="예시 뉴스",
                    published_at=date(2026, 5, 2))
    facts = []
    if metric:
        facts.append(make_manual_fact(brand_id="B1", entity="경쟁X", metric="views", value=120000, measured_at=DAY,
                                      source=src.title, source_id=src.id, evidence_id=cid, label="조회",
                                      status="eligible"))
    quote_fact = EN_QUOTE if english else "성수동 팝업 스토어에서 한정 컬렉션을 판매했다."
    claims = [
        ClaimRef(id=f"{cid}-a", kind="fact", parts=[Part(type="text", text="스트리트 브랜드와 한정 캡슐 컬렉션 출시")],
                 review_status="accepted", quote=quote_fact),
        ClaimRef(id=f"{cid}-b", kind="fact", parts=[Part(type="text", text="성수 팝업과 온라인 공식몰에서 동시 판매")],
                 review_status="accepted", quote=quote_fact),
        ClaimRef(id=f"{cid}-c", kind="interpretation", parts=[Part(type="text", text="한정판으로 젊은 층 방문 유도")],
                 review_status="accepted"),
        ClaimRef(id=f"{cid}-d", kind="interpretation", parts=[Part(type="text", text="오프라인 체험과 온라인 구매를 한 흐름으로 연결")],
                 review_status="accepted"),
    ]
    m = CaseMaterial(id=cid, brand_id="B1", entity="경쟁X", section_id="campaign", title=f"{cid} 캡슐 컬렉션", source=src,
                     activity_date=date(2026, 5, 1), metric_fact_ids=[f.id for f in facts], claims=claims,
                     review_status="accepted", ai_implication=implication,
                     asset=AssetRef(id=f"AS-{cid}", source_id=src.id, path=str(img), width=1280, height=720,
                                    review_status="accepted"))
    return m, facts


def _build(tmp: Path, cases):
    project, _, _ = load_fixture()
    project = project.model_copy(update={"enabled_slides": ["C2"]})
    mats = [m for m, _ in cases]
    extra = [f for _, fs in cases for f in fs]
    r = build_deck(BuildInputs(project=project, facts=extra, materials=mats,
                               generated_on=DAY))
    return r


def _blocks(slide):
    return {b.block_id: b for b in slide.blocks}


def test_no_figure_drops_summary_and_widens_image(tmp_path):
    r = _build(tmp_path, [_case(tmp_path, "EV-1")])
    slide = next(s for s in r.deck.slides if s.template_id == "case_detail.v1")
    b = _blocks(slide)
    assert "summary_bg" not in b and "figure_bg" not in b and "summary" not in b  # would only repeat 진행 방식
    assert isinstance(b["case_image"], ImageBlock) and b["case_image"].region.w == 640
    assert b["how_head"].region.y == 146  # 진행 방식 starts at the top of the right column


def test_figure_keeps_summary_box(tmp_path):
    r = _build(tmp_path, [_case(tmp_path, "EV-2", metric=True)])
    slide = next(s for s in r.deck.slides if s.template_id == "case_detail.v1")
    b = _blocks(slide)
    assert "summary_bg" in b and "figure_bg" in b and b["case_image"].region.w == 560
    assert any(p.type == "fact" for para in b["figure"].paragraphs for p in para.parts)


def test_implication_becomes_numbered_insights_not_a_takeaway(tmp_path):
    r = _build(tmp_path, [_case(tmp_path, "EV-3", metric=True, implication="한정판 협업을 팝업 체험과 묶는 흐름 참고")])
    slide = next(s for s in r.deck.slides if s.template_id == "case_detail.v1")
    b = _blocks(slide)
    assert not [x for x in slide.blocks if getattr(x, "role", None) == "takeaway"]
    titles = ["".join(p.rendered() for para in b[f"insight{i}_title"].paragraphs for p in para.parts) for i in range(2)]
    bodies = ["".join(p.rendered() for para in b[f"insight{i}_body"].paragraphs for p in para.parts) for i in range(2)]
    assert titles[0] == "적용 시사점" and "팝업 체험" in bodies[0]
    assert "오프라인 체험과 온라인 구매" in bodies[1]  # the interpretation not used as the headline
    assert "insight2_body" not in b  # figures stay in the summary box, not repeated as a card
    # the body stays above the insight row
    for x in slide.blocks:
        if x.block_id.startswith(("how", "quote")) and not x.block_id.startswith("quote_head_note"):
            assert x.region.y + x.region.h <= DETAIL_BODY_BOTTOM + 4, x.block_id


def test_english_quote_gets_korean_summary_and_link(tmp_path):
    assert is_foreign(EN_QUOTE) and not is_foreign("성수동 팝업 스토어에서 한정 컬렉션(Limited)을 판매했다.")
    r = _build(tmp_path, [_case(tmp_path, "EV-4", english=True), _case(tmp_path, "EV-5")])
    slides = [s for s in r.deck.slides if s.template_id == "case_detail.v1"]
    en, ko = (_blocks(s) for s in slides)
    first, second = en["quote0"].paragraphs
    assert "".join(p.rendered() for p in first.parts) == "스트리트 브랜드와 한정 캡슐 컬렉션 출시"
    link = second.parts[0]
    assert link.type == "link" and link.href == "https://example.com/EV-4" and "Samsonite" in link.text
    assert "한국어 요약" in "".join(p.rendered() for para in en["quote_head_note"].paragraphs for p in para.parts)
    assert ko["quote0"].paragraphs[0].parts[0].type == "quote"  # a Korean sentence stays verbatim

    qc = run_qc(r.deck, r.metrics.registry, lambda a: r.assets.get(a))
    issues = [i for i in qc.issues if i.severity == "block" and str(i.slide_id).startswith("C2")]
    assert not issues, issues


def test_case_detail_renders(tmp_path):
    r = _build(tmp_path, [_case(tmp_path, "EV-6", metric=True, implication="한정판 협업을 팝업 체험과 묶는 흐름 참고",
                                english=True), _case(tmp_path, "EV-7")])
    qc = run_qc(r.deck, r.metrics.registry, lambda a: r.assets.get(a))
    assert not [i for i in qc.issues if i.severity == "block" and str(i.slide_id).startswith("C2")]
    out = render_deck(r.deck, tmp_path / "c2.pptx",
                      lambda a: (r.assets[a].path, r.assets[a].width, r.assets[a].height))
    assert out.exists()


def test_ai_insight_cards_replace_rule_cards(tmp_path):
    """The build's P3-5 cards (or a person's) take the place of the rule cards on a case page."""
    from core.composition.build import body_fingerprint
    case = _case(tmp_path, "EV-8", implication="한정판 협업을 팝업 체험과 묶는 흐름 참고")
    slide = next(s for s in _build(tmp_path, [case]).deck.slides if s.template_id == "case_detail.v1")
    cards = [{"title": {"parts": [{"type": "text", "text": f"관찰 {name}"}]},
              "body_segments": {"parts": [{"type": "text", "text": f"'한정 캡슐' 원문이 보여 주는 점 {name}"}]}}
             for name in ("가", "나", "다")]
    project, _, _ = load_fixture()
    project = project.model_copy(update={"enabled_slides": ["C2"]})
    r = build_deck(BuildInputs(project=project, facts=[], materials=[case[0]], generated_on=DAY,
                               ai_writing={"insights": {slide.slide_id: {"fp": body_fingerprint(slide), "insights": cards}}}))
    b = _blocks(next(s for s in r.deck.slides if s.template_id == "case_detail.v1"))
    assert [b[f"insight{i}_title"].paragraphs[0].parts[0].text for i in range(3)] == ["관찰 가", "관찰 나", "관찰 다"]
