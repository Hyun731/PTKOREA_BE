"""Preview or import a private golden baseline into an existing project."""
from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.models import Project
from app.services.golden_import import import_golden_input_plan
from core.golden_baseline import load_golden_baseline
from core.golden_inputs import build_golden_input_plan
from core.schemas.project import Project as CoreProject


def _brand_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --brand-map value: {value}")
        name, brand_id = value.split("=", 1)
        name, brand_id = name.strip(), brand_id.strip()
        if not name or not brand_id:
            raise ValueError(f"invalid --brand-map value: {value}")
        mapping[name] = brand_id
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_dir")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--brand-map", action="append", default=[], metavar="BASELINE_BRAND=PROJECT_BRAND_ID")
    parser.add_argument("--apply", action="store_true", help="write accepted inputs; default is preview only")
    parser.add_argument("--output", help="write the complete plan/report JSON to this path")
    args = parser.parse_args()

    baseline = load_golden_baseline(args.baseline_dir, strict=True)
    engine = make_engine(args.database_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with Session() as db:
        project = db.get(Project, args.project_id)
        if project is None:
            raise SystemExit(f"project not found: {args.project_id}")
        plan = build_golden_input_plan(
            baseline,
            CoreProject.model_validate(project.config),
            project.id,
            _brand_mapping(args.brand_map),
        )
        result = import_golden_input_plan(db, project, plan) if args.apply else plan.summary()

    report = {
        "mode": "apply" if args.apply else "preview",
        "result": result,
        "unsupported_facts": [item.model_dump(mode="json") for item in plan.unsupported_facts],
        "claims_with_unsupported_facts": [
            {"claim_id": item.baseline_claim_id, "fact_ids": item.unsupported_fact_ids}
            for item in plan.claims if item.unsupported_fact_ids
        ],
        "claims_with_unbound_numbers": [
            item.baseline_claim_id for item in plan.claims if item.has_unbound_numbers
        ],
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
