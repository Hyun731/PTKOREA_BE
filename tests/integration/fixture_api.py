"""Test-only fixture setup through the real project and CSV upload APIs."""
from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.models import Project

FIXTURES = Path(__file__).parent.parent / "fixtures" / "quantitative_samples"
FIXTURE_SLIDES = ["cover", "index", "divider", "1-1", "1-6", "2-8a", "2-8b", "2-8c", "2-8d", "3-1", "C1",
                  "5-recap", "A-source", "end"]


def create_fixture_project(client) -> dict:
    body = json.loads((FIXTURES / "project.json").read_text(encoding="utf-8"))
    body["report_profile"] = "diagnostic"
    response = client.post("/v1/projects", json=body)
    assert response.status_code == 201, response.text
    project = response.json()
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        config = dict(row.config)
        config["enabled_slides"] = FIXTURE_SLIDES
        config["section_windows"] = [*config.get("section_windows", []), {
            "section_id": "campaign", "label": "9M", "start": "2026-01-01", "end": "2026-09-30", "source": "user",
        }]
        row.config = config
        db.commit()
    refreshed = client.get(f"/v1/projects/{project['id']}")
    assert refreshed.status_code == 200, refreshed.text
    return refreshed.json()


def upload_fixture_batches(client, project_id: str, posts: str = "posts.csv") -> list[dict]:
    rows = []
    for kind, filename in (("facts", "facts.csv"), ("posts", posts)):
        payload = (FIXTURES / filename).read_bytes()
        if kind == "facts":
            payload = payload.replace(b"synthetic_fixture", b"test_fixture")
        response = client.post(
            f"/v1/projects/{project_id}/imports",
            data={"kind": kind},
            files={"file": (filename, payload, "text/csv")},
        )
        assert response.status_code == 201, response.text
        rows.append(response.json())
    return rows
