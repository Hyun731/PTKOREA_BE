"""Phase 3-2 업종 KPI(M2): 자사·경쟁사 구분, 공개 대체 지표 표시, 출처·기준 시점 필수."""
from datetime import date

from app.services.research import validate_extraction
from core.composition.cases import kpi_pages
from core.composition.chrome import PartFactory
from core.ingestion.manual import make_manual_fact
from core.metrics.registry import FactRegistry
from core.schemas.materials import CaseMaterial, SourceRef


def _material(idx: int, entity: str, fact_id: str, asof=date(2026, 3, 1)) -> CaseMaterial:
    src = SourceRef(id=f"SRC-{idx}", title=f"출처 {idx}", publisher=f"매체{idx}", published_at=asof)
    return CaseMaterial(id=f"EV-{idx}", section_id="market_kpi", entity=entity, title=f"항목 {idx}", source=src,
                        review_status="accepted", metric_fact_ids=[fact_id])


def test_kpi_page_marks_self_vs_competitor_and_substituted():
    f_self = make_manual_fact(brand_id="B1", entity="자사A", metric="count", value="1000",
                              measured_at=date(2026, 3, 1), source="s", label="거래량")
    f_comp = make_manual_fact(brand_id="B1", entity="경쟁사B", metric="count", value="2000",
                              measured_at=date(2026, 3, 1), source="s", label="ARPU", dims={"substituted": "true"})
    f_self = f_self.model_copy(update={"verification_status": "eligible"})
    f_comp = f_comp.model_copy(update={"verification_status": "eligible"})
    pf = PartFactory(FactRegistry([f_self, f_comp]))
    m_self = _material(1, "자사A", f_self.id)
    m_comp = _material(2, "경쟁사B", f_comp.id)
    slides = kpi_pages([m_self, m_comp], pf, "자사A", badge=[])
    assert len(slides) == 1
    table = next(b for b in slides[0].blocks if b.block_id == "table")
    rows = table.rows
    assert [r.cells[0].paragraphs[0].plain() for r in rows] == ["자사", "경쟁사"]  # 자사가 먼저
    assert "공개 지표로 대체" in rows[1].cells[1].paragraphs[0].plain()
    assert "공개 지표로 대체" not in rows[0].cells[1].paragraphs[0].plain()


def test_kpi_page_drops_facts_without_a_known_date():
    f = make_manual_fact(brand_id="B1", entity="자사A", metric="count", value="1000",
                         measured_at=date(2026, 3, 1), source="s", label="거래량")
    f = f.model_copy(update={"verification_status": "eligible"})
    pf = PartFactory(FactRegistry([f]))
    src = SourceRef(id="SRC-1", title="출처 1")  # published_at 없음, activity_date도 없음
    m = CaseMaterial(id="EV-1", section_id="market_kpi", entity="자사A", title="항목", source=src,
                     review_status="accepted", metric_fact_ids=[f.id])
    assert kpi_pages([m], pf, "자사A", badge=[]) == []  # 기준 시점 없는 숫자는 쓰지 않는다


def test_validate_extraction_keeps_the_substituted_flag():
    text = "2025년 거래량은 12000000건으로 집계됐다."
    data = {"facts": [{"label": "거래량", "metric": "count", "value": "12000000",
                       "quote": "2025년 거래량은 12000000건으로 집계됐다.", "substituted": True}]}
    facts, _, _ = validate_extraction(data, text)
    assert facts[0]["substituted"] is True


def test_validate_extraction_defaults_substituted_to_false():
    text = "2025년 거래량은 12000000건으로 집계됐다."
    data = {"facts": [{"label": "거래량", "metric": "count", "value": "12000000",
                       "quote": "2025년 거래량은 12000000건으로 집계됐다."}]}  # substituted 없음
    facts, _, _ = validate_extraction(data, text)
    assert facts[0]["substituted"] is False
