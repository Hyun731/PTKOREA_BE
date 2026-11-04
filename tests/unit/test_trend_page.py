"""Phase 3-4 검색 추이(TR1): 브랜드·카테고리 지수 선 차트 + 연관 검색어, 채택된 숫자만 쓴다."""
from datetime import date
from types import SimpleNamespace

from core.composition.chrome import PartFactory
from core.composition.quant import QuantContext, trend_page
from core.ingestion.trends_index import trends_monthly_fact
from core.metrics.registry import FactRegistry
from core.schemas.project import Project


def _project(categories=None) -> Project:
    return Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"}, "enabled_slides": [],
        "brands": [{"id": "B1", "name": "나이키", "competitors": ["아디다스"],
                   "categories": categories or ["스포츠웨어"]}]})


def _ctx(facts: list, categories=None) -> QuantContext:
    registry = FactRegistry(facts)
    metrics = SimpleNamespace(registry=registry)
    return QuantContext(project=_project(categories), metrics=metrics, findings=[], pf=PartFactory(registry),
                        config=None, synthetic=False)


def _fact(entity: str, month: str, index: float, eligible: bool = True):
    f = trends_monthly_fact(brand_id="B1", entity=entity, month=month, index=index, measured_at=date(2026, 9, 1))
    return f.model_copy(update={"verification_status": "eligible" if eligible else "candidate"})


def test_builds_a_line_series_per_keyword_with_eligible_points_only():
    facts = [_fact("나이키", "2026-07", 40), _fact("나이키", "2026-08", 60),
            _fact("스포츠웨어", "2026-07", 50), _fact("스포츠웨어", "2026-08", 55, eligible=False)]
    slide = trend_page(_ctx(facts), related=["나이키 신상"])
    assert slide is not None
    chart = next(b for b in slide.blocks if b.block_id == "chart")
    by_entity = {s.entity: s for s in chart.series}
    assert [p.value for p in by_entity["나이키"].points] == [40.0, 60.0]
    assert [p.value for p in by_entity["스포츠웨어"].points] == [50.0, None]  # candidate point stays a gap


def test_shows_related_queries_when_present():
    facts = [_fact("나이키", "2026-07", 40)]
    slide = trend_page(_ctx(facts), related=["나이키 신상", "나이키 세일"])
    related_block = next(b for b in slide.blocks if b.block_id == "related")
    text = related_block.paragraphs[0].plain()
    assert "나이키 신상" in text and "나이키 세일" in text


def test_returns_none_without_any_eligible_facts():
    assert trend_page(_ctx([]), related=[]) is None
    assert trend_page(_ctx([_fact("나이키", "2026-07", 40, eligible=False)]), related=[]) is None


def test_skips_category_series_when_it_equals_the_brand_name():
    facts = [_fact("나이키", "2026-07", 40)]
    slide = trend_page(_ctx(facts, categories=["나이키"]), related=[])
    chart = next(b for b in slide.blocks if b.block_id == "chart")
    assert [s.entity for s in chart.series] == ["나이키"]  # 카테고리가 브랜드명과 같음 — 두 번째 계열 없음
