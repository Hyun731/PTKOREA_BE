"""M1's numbered '읽는 법' takeaways: one per row, preferring the interpretation claim."""
from datetime import date

from core.composition.cases import market_page
from core.composition.chrome import PartFactory
from core.metrics.registry import FactRegistry
from core.schemas.materials import CaseMaterial, ClaimRef, SourceRef
from core.schemas.slidespec import Part, TextBlock


def _market_material(idx: int, fact_text: str, interp_text: str) -> CaseMaterial:
    src = SourceRef(id=f"SRC-{idx}", title=f"출처 {idx}", publisher="합성 출처", published_at=date(2026, 8, 1))
    claims = [
        ClaimRef(id=f"CL-{idx}a", kind="fact", parts=[Part(type="text", text=fact_text)], review_status="accepted"),
        ClaimRef(id=f"CL-{idx}b", kind="interpretation", parts=[Part(type="text", text=interp_text)], review_status="accepted"),
    ]
    return CaseMaterial(id=f"EV-{idx}", section_id="market", title=f"항목 {idx}", source=src, claims=claims,
                        review_status="accepted")


def test_market_page_has_numbered_insights():
    pf = PartFactory(FactRegistry())
    materials = [_market_material(1, "사실 1", "해석 1"), _market_material(2, "사실 2", "해석 2"),
                _market_material(3, "사실 3", "해석 3")]
    slide = market_page(materials, pf, badge=[])
    assert slide is not None
    insights = next(b for b in slide.blocks if isinstance(b, TextBlock) and b.block_id == "insights")
    assert [p.bullet for p in insights.paragraphs] == ["①", "②", "③"]
    assert all("해석" in p.plain() for p in insights.paragraphs)
    assert insights.region.h > 0


def test_market_page_insight_falls_back_to_fact_without_interpretation():
    src = SourceRef(id="SRC-9", title="출처 9")
    m = CaseMaterial(id="EV-9", section_id="market", title="항목 9", source=src,
                     claims=[ClaimRef(id="CL-9a", kind="fact", parts=[Part(type="text", text="사실만 있음")],
                                      review_status="accepted")], review_status="accepted")
    pf = PartFactory(FactRegistry())
    slide = market_page([m], pf, badge=[])
    insights = next(b for b in slide.blocks if isinstance(b, TextBlock) and b.block_id == "insights")
    assert "사실만 있음" in insights.paragraphs[0].plain()
