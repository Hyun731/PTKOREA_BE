from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Claim, FactRow, Material, Project, Source
from app.services.golden_import import import_golden_input_plan
from app.services.inputs import load_inputs
from core.golden_baseline import load_golden_baseline
from core.golden_inputs import build_golden_input_plan
from core.schemas.project import Project as CoreProject


FIXTURE = Path(__file__).parents[1] / "fixtures" / "golden_baseline"


def _ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def test_imports_accepted_inputs_idempotently(client):
    created = _ok(client.post("/v1/projects", json={
        "name": "Golden import integration",
        "client": "Synthetic client",
        "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [
            {"id": "B1", "name": "Alpha Local", "competitors": ["Rival A"]},
            {"id": "B2", "name": "Beta Local", "competitors": ["Rival B"]},
            {"id": "B3", "name": "Gamma Local", "competitors": ["Rival C"]},
        ],
    }), 201)
    with SessionLocal() as db:
        project = db.get(Project, created["id"])
        plan = build_golden_input_plan(
            load_golden_baseline(FIXTURE, strict=True),
            CoreProject.model_validate(project.config),
            project.id,
            {"Brand Alpha": "B1", "Brand Beta": "B2", "Brand Gamma": "B3"},
        )
        first = import_golden_input_plan(db, project, plan)
        second = import_golden_input_plan(db, project, plan)
        assert first["sources_created"] == first["materials_created"] == 3
        assert first["facts_created"] == 3
        assert first["claims_created"] == 3
        assert second["sources_created"] == second["materials_created"] == 0
        assert second["facts_created"] == second["claims_created"] == 0
        assert db.scalar(select(func.count()).select_from(Source).where(Source.project_id == project.id)) == 3
        assert db.scalar(select(func.count()).select_from(Material).where(Material.project_id == project.id)) == 3
        assert db.scalar(select(func.count()).select_from(FactRow).where(FactRow.project_id == project.id)) == 3
        assert db.scalar(select(func.count()).select_from(Claim).where(Claim.project_id == project.id)) == 3
        inputs = load_inputs(db, project)
        assert all(fact.verification_status == "eligible" for fact in inputs.facts)
        assert all(material.review_status == "accepted" for material in inputs.materials)
        assert sum(len(material.claims) for material in inputs.materials) == 3
        assert sum(claim.review_status == "accepted" for material in inputs.materials for claim in material.claims) == 3
