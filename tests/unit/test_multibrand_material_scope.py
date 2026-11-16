from types import SimpleNamespace

from core.composition.build import _material_belongs_to_brand
from core.schemas.project import Project


def _project() -> Project:
    return Project.model_validate({
        "name": "p",
        "client": "c",
        "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "enabled_slides": [],
        "brands": [
            {"id": "B1", "name": "브랜드A", "competitors": ["공통경쟁", "경쟁1"]},
            {"id": "B2", "name": "브랜드B", "competitors": ["공통경쟁", "경쟁2"]},
        ],
    })


def _material(brand_id, entity, related=()):
    return SimpleNamespace(brand_id=brand_id, entity=entity, related_brand_ids=list(related))


def test_shared_competitor_uses_explicit_primary_brand():
    project = _project()
    material = _material("B1", "공통경쟁")

    assert _material_belongs_to_brand(material, project.brands[0], project, 0)
    assert not _material_belongs_to_brand(material, project.brands[1], project, 1)


def test_related_brand_explicitly_shares_material():
    project = _project()
    material = _material("B1", "공통경쟁", related=["B2"])

    assert _material_belongs_to_brand(material, project.brands[0], project, 0)
    assert _material_belongs_to_brand(material, project.brands[1], project, 1)


def test_unique_competitor_still_follows_its_only_brand():
    project = _project()
    material = _material("B1", "경쟁2")

    assert not _material_belongs_to_brand(material, project.brands[0], project, 0)
    assert _material_belongs_to_brand(material, project.brands[1], project, 1)
