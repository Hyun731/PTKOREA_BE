"""Phase 3-3 사례 귀속 정리: 캠페인 자료는 주로 다루는 자사 브랜드 하나에만 붙는다."""
from app.models import Material, ResearchItem
from app.services.research import reassign_primary_brand
from core.schemas.project import Project


def _core(n: int = 2) -> Project:
    return Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"}, "enabled_slides": [],
        "brands": [{"id": f"B{i}", "name": f"브랜드{chr(64 + i)}", "competitors": [f"경쟁{i}"]} for i in range(1, n + 1)]})


def _item(brand_id: str, entity: str, role: str = "self", section_id: str = "campaign") -> ResearchItem:
    return ResearchItem(role=role, brand_id=brand_id, entity=entity, section_id=section_id)


def _mat(brand_id: str, entity: str, section_id: str = "campaign") -> Material:
    return Material(brand_id=brand_id, entity=entity, section_id=section_id, related_brand_ids=[])


def test_reassigns_to_the_brand_the_ai_names_as_primary():
    core = _core()
    item = _item("B2", "브랜드B")
    m = _mat("B2", "브랜드B")
    reassign_primary_brand(m, item, core, {"primary_brand": "브랜드A", "related_brands": []})
    assert (m.brand_id, m.entity) == ("B1", "브랜드A")
    assert m.related_brand_ids == []


def test_keeps_the_researched_brand_when_ai_confirms_it():
    core = _core()
    item = _item("B1", "브랜드A")
    m = _mat("B1", "브랜드A")
    reassign_primary_brand(m, item, core, {"primary_brand": None, "related_brands": []})
    assert (m.brand_id, m.entity) == ("B1", "브랜드A")


def test_records_other_self_brands_as_related_not_reassigned():
    core = _core(3)
    item = _item("B1", "브랜드A")
    m = _mat("B1", "브랜드A")
    reassign_primary_brand(m, item, core, {"primary_brand": None, "related_brands": ["브랜드B", "브랜드C"]})
    assert (m.brand_id, m.entity) == ("B1", "브랜드A")  # 주 대상은 그대로
    assert set(m.related_brand_ids) == {"B2", "B3"}  # 함께 등장한 다른 자사 브랜드만 기록


def test_ignores_unknown_or_competitor_names():
    core = _core()
    item = _item("B1", "브랜드A")
    m = _mat("B1", "브랜드A")
    reassign_primary_brand(m, item, core, {"primary_brand": "경쟁1", "related_brands": ["경쟁2"]})
    assert (m.brand_id, m.entity) == ("B1", "브랜드A")  # 경쟁사 이름은 재귀속 대상이 아님
    assert m.related_brand_ids == []


def test_only_applies_to_self_role_campaign_materials():
    core = _core()
    for role, section in (("competitor", "campaign"), ("self", "market"), ("self", "voc")):
        item = _item("B1", "브랜드A", role=role, section_id=section)
        m = _mat("B1", "브랜드A", section_id=section)
        reassign_primary_brand(m, item, core, {"primary_brand": "브랜드B", "related_brands": []})
        assert (m.brand_id, m.entity) == ("B1", "브랜드A")  # 캠페인·자사 항목이 아니면 손대지 않음
