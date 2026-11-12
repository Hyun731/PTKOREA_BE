"""P3-7 synthesis pages keep citations, typed facts, and safe recap layouts."""
from datetime import date
from decimal import Decimal

from pptx import Presentation

from core.composition.chrome import PartFactory
from core.composition.synthesis import es_page, insight_page, swot_page
from core.metrics.registry import FactRegistry
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.facts import Fact
from core.schemas.slidespec import DeckSpec, TextBlock


def _fact() -> Fact:
    return Fact(
        id="F-share", content_hash="h", brand_id="B1", entity="브랜드A", metric="share",
        value=Decimal("42.5"), unit="percent", period_start=date(2026, 1, 1),
        period_end=date(2026, 9, 30), measured_at=date(2026, 10, 12), source="fixture",
        confidence="verified", verification_status="eligible",
    )


def _line(text: str, ref: str = "2-8a", *, fact_ref: str | None = None, source_url: str | None = None) -> dict:
    return {"text": text, "ref": ref, "fact_ref": fact_ref, "source_url": source_url}


def _deck(*slides) -> DeckSpec:
    return DeckSpec(deck_id="D1", project_name="종합 장표", slides=list(slides), plan=[])


def _text_blocks(slide):
    return [block for block in slide.blocks if isinstance(block, TextBlock)]


def test_insight_page_renders_fact_and_source_citation(tmp_path):
    fact = _fact()
    registry = FactRegistry([fact])
    slide = insight_page({
        "lead": "검색 경쟁력 변화가 핵심 관찰로 연결",
        "insights": [{
            "title": "검색 우위 축소",
            "body": "경쟁 세트 안 검색 점유 우위 축소",
            "ref": "2-8a",
            "fact_ref": fact.id,
            "source_url": "https://example.com/search",
        }],
    }, PartFactory(registry))

    body = slide.block("panel0_body")
    parts = body.paragraphs[0].parts
    assert any(part.type == "fact" and part.fact_id == fact.id and part.display == "42.5%" for part in parts)
    assert any(part.type == "link" and part.text == "[2-8a]" and part.href == "https://example.com/search" for part in parts)
    assert not [issue for issue in run_qc(_deck(slide), registry, lambda _: None).issues
                if issue.severity == "block" and issue.code != "NO_DATA_SLIDES"]

    path = render_deck(_deck(slide), tmp_path / "synthesis.pptx")
    rendered = Presentation(str(path)).slides[0]
    shapes = {shape.name: shape for shape in rendered.shapes}
    assert "42.5%" in shapes["panel0_body"].text
    assert "[2-8a]" in shapes["panel0_body"].text


def test_es_page_places_three_insights_above_three_c_panels():
    lines = {
        "company": [_line("자사 채널 운영 흐름이 안정적")],
        "competitor": [_line("경쟁사 검색 존재감이 확대")],
        "customer": [_line("소비자 불편이 제품 경험에 집중")],
        "task": "검색 우위 회복과 제품 경험 보완 필요",
        "insights": [
            {"title": "검색", "body": "검색 우위 축소 흐름", "ref": "2-8a"},
            {"title": "콘텐츠", "body": "실사용 콘텐츠 보강 여지", "ref": "BL1"},
            {"title": "경험", "body": "제품 경험 불편 해소 필요", "ref": "PP1"},
        ],
    }
    slide = es_page(lines)

    summary = slide.block("summary")
    panel_heads = [block for block in _text_blocks(slide) if block.role == "panel_header"]
    assert len(summary.paragraphs) == 3
    assert [paragraph.bullet for paragraph in summary.paragraphs] == ["1.", "2.", "3."]
    assert len(panel_heads) == 3
    assert summary.region.y + summary.region.h < min(block.region.y for block in panel_heads)


def test_swot_page_is_two_by_two_and_stays_inside_body_band():
    slide = swot_page({
        "lead": "자사 강점을 지키며 소비자 불편을 해소할 기회",
        "S": [_line("자사 채널 운영의 일관성")],
        "W": [_line("검색 존재감의 상대적 약화")],
        "O": [_line("실사용 정보 수요 확대")],
        "T": [_line("경쟁사 콘텐츠 점유 확대")],
    })

    heads = {block.block_id: block for block in _text_blocks(slide) if block.role == "panel_header"}
    assert len(heads) == 4
    assert heads["panel0_head"].region.y == heads["panel1_head"].region.y
    assert heads["panel2_head"].region.y == heads["panel3_head"].region.y
    assert heads["panel0_head"].region.x == heads["panel2_head"].region.x
    assert heads["panel1_head"].region.x == heads["panel3_head"].region.x
    assert heads["panel2_head"].region.y > heads["panel0_head"].region.y
    assert max(block.region.y + block.region.h for block in slide.blocks) <= 720
