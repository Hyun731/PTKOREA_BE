"""Persist a golden input plan without overwriting existing project evidence."""
from __future__ import annotations

import json
import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, FactRow, Material, Project, Source
from core.golden_inputs import GoldenInputPlan
from core.schemas.facts import Fact


def import_golden_input_plan(db: Session, project: Project, plan: GoldenInputPlan) -> dict:
    if project.id != plan.project_id:
        raise ValueError("plan project_id does not match the target project")

    existing_sources = {row.id for row in db.scalars(select(Source).where(Source.project_id == project.id))}
    existing_materials = {row.id for row in db.scalars(select(Material).where(Material.project_id == project.id))}
    existing_claims = {row.id for row in db.scalars(select(Claim).where(Claim.project_id == project.id))}
    existing_facts = {row.fact_id for row in db.scalars(select(FactRow).where(FactRow.project_id == project.id))}
    counts = {
        "sources_created": 0,
        "materials_created": 0,
        "facts_created": 0,
        "claims_created": 0,
        "already_present": 0,
    }

    for item in plan.materials:
        if item.source_id not in existing_sources:
            db.add(Source(
                id=item.source_id,
                project_id=project.id,
                title=item.source_title,
                original_url=item.source_url,
                publisher=item.publisher,
                published_at=date.fromisoformat(item.published_at) if item.published_at else None,
                content_hash=hashlib.sha256(
                    f"{plan.baseline_id}:{project.id}:{item.page}".encode("utf-8")
                ).hexdigest(),
                source_type="report",
                access_status="ok",
                text=item.excerpt or None,
            ))
            existing_sources.add(item.source_id)
            counts["sources_created"] += 1
            db.flush()
        else:
            counts["already_present"] += 1
        if item.material_id not in existing_materials:
            db.add(Material(
                id=item.material_id,
                project_id=project.id,
                source_id=item.source_id,
                brand_id=item.brand_id,
                entity=item.entity,
                section_id=item.section_id,
                title=item.title,
                excerpt=item.excerpt,
                comment=f"Golden baseline {plan.baseline_id} · page {item.page}",
                input_path="manual",
                review_status="accepted",
                reviewed_by="golden-baseline",
            ))
            existing_materials.add(item.material_id)
            counts["materials_created"] += 1
        else:
            counts["already_present"] += 1
    db.flush()

    for item in plan.facts:
        if item.fact_id in existing_facts:
            counts["already_present"] += 1
            continue
        fact = Fact(
            id=item.fact_id,
            content_hash=item.content_hash,
            brand_id=item.brand_id,
            entity=item.entity,
            metric=item.metric,
            value=item.value,
            unit=item.unit,
            period_start=date.fromisoformat(item.period_start),
            period_end=date.fromisoformat(item.period_end),
            measured_at=date.fromisoformat(item.measured_at),
            source=item.source,
            source_id=item.source_id,
            evidence_id=item.evidence_id,
            url=item.url,
            method=item.method,
            confidence="verified",
            verification_status="eligible",
            label=item.label,
        )
        db.add(FactRow(
            project_id=project.id,
            fact_id=fact.id,
            origin="manual",
            material_id=item.material_id,
            data=json.loads(fact.model_dump_json()),
            verification_status="eligible",
            review_note=f"Imported from golden baseline {plan.baseline_id}",
        ))
        existing_facts.add(item.fact_id)
        counts["facts_created"] += 1

    for item in plan.claims:
        if item.claim_id in existing_claims:
            counts["already_present"] += 1
            continue
        db.add(Claim(
            id=item.claim_id,
            project_id=project.id,
            material_id=item.material_id,
            kind=item.kind,
            parts=[part.model_dump(exclude_none=True) for part in item.parts],
            evidence_ids=[item.material_id],
            fact_ids=item.fact_ids,
            author="user",
            review_status=item.review_status,
        ))
        existing_claims.add(item.claim_id)
        counts["claims_created"] += 1

    db.commit()
    return {**plan.summary(), **counts}
