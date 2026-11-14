"""Map a validated golden baseline into customer-agnostic application inputs."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.golden_baseline import BaselineClaim, BaselineFact, GoldenBaseline
from core.schemas.facts import MANUAL_METRICS
from core.schemas.project import Project
from core.schemas.slidespec import Part


ClaimKind = Literal["fact", "interpretation", "recommendation"]
ClaimReviewStatus = Literal["pending", "accepted"]

UNIT_METRICS = {
    "count": "count",
    "건": "count",
    "개": "count",
    "명": "count",
    "회": "count",
    "percent": "percent",
    "%": "percent",
    "krw": "amount_krw",
    "원": "amount_krw",
    "usd": "amount_usd",
    "달러": "amount_usd",
    "pp": "percentage_point",
    "rank": "rank",
    "위": "rank",
    "score": "score",
    "점": "score",
    "ratio": "ratio",
    "배": "ratio",
    "days": "duration_days",
    "일": "duration_days",
    "months": "duration_months",
    "개월": "duration_months",
    "years": "duration_years",
    "년": "duration_years",
    "group": "group_count",
    "그룹": "group_count",
}

SECTION_MAP = {
    "market": "market",
    "brand": "campaign",
    "owned": "campaign",
    "competitor": "campaign",
    "summary": "campaign",
}

CLAIM_KIND_MAP: dict[str, ClaimKind] = {
    "headline": "fact",
    "evidence": "fact",
    "insight": "interpretation",
    "conclusion": "interpretation",
    "recommendation": "recommendation",
}


def stable_id(prefix: str, *parts: object, length: int = 12) -> str:
    raw = ":".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


class UnsupportedFact(BaseModel):
    baseline_fact_id: str
    brand: str
    metric: str
    unit: str
    reason: str


class PlannedFact(BaseModel):
    baseline_fact_id: str
    fact_id: str
    material_id: str
    brand_id: str
    entity: str
    metric: str
    value: Decimal
    unit: str
    label: str
    period_start: str
    period_end: str
    measured_at: str
    source: str
    source_id: str
    evidence_id: str
    url: Optional[str] = None
    method: Optional[str] = None
    content_hash: str


class PlannedClaim(BaseModel):
    baseline_claim_id: str
    claim_id: str
    material_id: str
    kind: ClaimKind
    text: str
    parts: list[Part]
    fact_ids: list[str] = Field(default_factory=list)
    unsupported_fact_ids: list[str] = Field(default_factory=list)
    has_unbound_numbers: bool = False
    review_status: ClaimReviewStatus


class PlannedMaterial(BaseModel):
    page: int
    source_id: str
    material_id: str
    brand_id: Optional[str] = None
    entity: Optional[str] = None
    section_id: str
    title: str
    source_title: str
    source_url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    excerpt: str = ""
    fact_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class GoldenInputPlan(BaseModel):
    baseline_id: str
    project_id: str
    brand_mapping: dict[str, str]
    materials: list[PlannedMaterial]
    facts: list[PlannedFact]
    claims: list[PlannedClaim]
    unsupported_facts: list[UnsupportedFact]

    def summary(self) -> dict:
        return {
            "baseline_id": self.baseline_id,
            "project_id": self.project_id,
            "brands": self.brand_mapping,
            "materials": len(self.materials),
            "facts": len(self.facts),
            "claims": len(self.claims),
            "accepted_claims": sum(item.review_status == "accepted" for item in self.claims),
            "pending_claims": sum(item.review_status == "pending" for item in self.claims),
            "unsupported_facts": len(self.unsupported_facts),
            "unsupported_by_reason": dict(sorted(_count(item.reason for item in self.unsupported_facts).items())),
        }


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _validate_brand_mapping(baseline: GoldenBaseline, project: Project, mapping: dict[str, str]) -> None:
    missing = sorted(set(baseline.manifest.brands) - set(mapping))
    if missing:
        raise ValueError(f"missing brand mappings: {', '.join(missing)}")
    project_ids = {brand.id for brand in project.brands}
    unknown = sorted(set(mapping.values()) - project_ids)
    if unknown:
        raise ValueError(f"unknown project brand ids: {', '.join(unknown)}")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("each baseline brand must map to a different project brand")


def _metric_for(fact: BaselineFact) -> tuple[Optional[str], Optional[str]]:
    unit = fact.unit.strip().lower()
    if fact.metric in MANUAL_METRICS:
        expected = MANUAL_METRICS[fact.metric]
        if unit == expected or UNIT_METRICS.get(unit) == fact.metric:
            return fact.metric, None
        return None, f"metric {fact.metric} requires unit {expected}"
    metric = UNIT_METRICS.get(unit)
    if metric is None:
        return None, f"unsupported unit {fact.unit}"
    return metric, None


def _number_candidates(fact: BaselineFact) -> list[str]:
    value = fact.value
    raw = format(value, "f")
    trimmed = raw.rstrip("0").rstrip(".") if "." in raw else raw
    candidates = {raw, trimmed}
    if value == value.to_integral_value():
        integer = int(value)
        candidates.update({str(integer), f"{integer:,}"})
    if fact.unit.strip().lower() in {"percent", "%"}:
        candidates.update({f"{trimmed}%", f"{trimmed} %"})
    if fact.unit.strip().lower() in {"krw", "원"} and value == value.to_integral_value():
        integer = int(value)
        candidates.update({f"{integer}원", f"{integer:,}원"})
    suffixes = {
        "usd": ["달러"],
        "score": ["점"],
        "ratio": ["배"],
        "days": ["일"],
        "months": ["개월"],
        "years": ["년"],
        "group": ["개 그룹", "그룹"],
        "pp": ["pp"],
    }
    for suffix in suffixes.get(fact.unit.strip().lower(), []):
        candidates.add(f"{trimmed}{suffix}")
    return sorted((candidate for candidate in candidates if candidate), key=len, reverse=True)


def _claim_parts(text: str, facts: list[tuple[BaselineFact, PlannedFact]]) -> list[Part]:
    matches: list[tuple[int, int, PlannedFact]] = []
    occupied: list[tuple[int, int]] = []
    for baseline_fact, planned_fact in facts:
        found = None
        for candidate in _number_candidates(baseline_fact):
            pattern = re.compile(rf"(?<![\d.]){re.escape(candidate)}(?![\d.])")
            for match in pattern.finditer(text):
                span = match.span()
                if not any(span[0] < end and start < span[1] for start, end in occupied):
                    found = (span[0], span[1], planned_fact)
                    break
            if found:
                break
        if found:
            matches.append(found)
            occupied.append((found[0], found[1]))
    if not matches:
        return [Part(type="text", text=text)]
    parts: list[Part] = []
    cursor = 0
    for start, end, fact in sorted(matches):
        if cursor < start:
            parts.append(Part(type="text", text=text[cursor:start]))
        parts.append(Part(type="fact", fact_id=fact.fact_id, bold=True))
        cursor = end
    if cursor < len(text):
        parts.append(Part(type="text", text=text[cursor:]))
    return parts


def build_golden_input_plan(
    baseline: GoldenBaseline,
    project: Project,
    project_id: str,
    brand_mapping: dict[str, str],
) -> GoldenInputPlan:
    _validate_brand_mapping(baseline, project, brand_mapping)
    brands_by_id = {brand.id: brand for brand in project.brands}
    slides = {slide.page: slide for slide in baseline.slides}
    facts_by_page: dict[int, list[BaselineFact]] = defaultdict(list)
    claims_by_page: dict[int, list[BaselineClaim]] = defaultdict(list)
    for fact in baseline.facts:
        facts_by_page[fact.evidence_page].append(fact)
    for claim in baseline.claims:
        claims_by_page[claim.evidence_page].append(claim)

    planned_facts: list[PlannedFact] = []
    unsupported: list[UnsupportedFact] = []
    planned_by_baseline_id: dict[str, tuple[BaselineFact, PlannedFact]] = {}
    material_keys = sorted(set(facts_by_page) | set(claims_by_page))
    material_ids = {
        page: stable_id("EV", baseline.manifest.baseline_id, project_id, page) for page in material_keys
    }
    source_ids = {
        page: stable_id("SRC", baseline.manifest.baseline_id, project_id, page) for page in material_keys
    }

    for fact in baseline.facts:
        metric, reason = _metric_for(fact)
        if fact.brand == "ALL":
            reason = reason or "project-level facts require an explicit brand"
        if reason:
            unsupported.append(UnsupportedFact(
                baseline_fact_id=fact.fact_id, brand=fact.brand, metric=fact.metric, unit=fact.unit, reason=reason,
            ))
            continue
        brand_id = brand_mapping[fact.brand]
        fact_id = stable_id("F", baseline.manifest.baseline_id, fact.fact_id, length=20)
        planned = PlannedFact(
            baseline_fact_id=fact.fact_id,
            fact_id=fact_id,
            material_id=material_ids[fact.evidence_page],
            brand_id=brand_id,
            entity=brands_by_id[brand_id].name,
            metric=metric,
            value=fact.value,
            unit=MANUAL_METRICS[metric],
            label=fact.metric,
            period_start=fact.period_start.isoformat(),
            period_end=fact.period_end.isoformat(),
            measured_at=fact.measured_on.isoformat(),
            source=fact.source_name,
            source_id=source_ids[fact.evidence_page],
            evidence_id=material_ids[fact.evidence_page],
            url=fact.source_url,
            method=fact.calculation,
            content_hash=hashlib.sha256(
                f"{baseline.manifest.baseline_id}:{fact.fact_id}:{fact.value}:{fact.unit}".encode("utf-8")
            ).hexdigest(),
        )
        planned_facts.append(planned)
        planned_by_baseline_id[fact.fact_id] = (fact, planned)

    planned_claims: list[PlannedClaim] = []
    for claim in baseline.claims:
        compatible = [planned_by_baseline_id[fact_id] for fact_id in claim.fact_ids if fact_id in planned_by_baseline_id]
        unsupported_ids = [fact_id for fact_id in claim.fact_ids if fact_id not in planned_by_baseline_id]
        parts = _claim_parts(claim.text, compatible)
        has_unbound_numbers = any(part.type == "text" and part.text and re.search(r"\d", part.text) for part in parts)
        planned_claims.append(PlannedClaim(
            baseline_claim_id=claim.claim_id,
            claim_id=stable_id("CL", baseline.manifest.baseline_id, project_id, claim.claim_id),
            material_id=material_ids[claim.evidence_page],
            kind=CLAIM_KIND_MAP[claim.kind],
            text=claim.text,
            parts=parts,
            fact_ids=[planned.fact_id for _, planned in compatible],
            unsupported_fact_ids=unsupported_ids,
            has_unbound_numbers=has_unbound_numbers,
            review_status="pending" if unsupported_ids or has_unbound_numbers else "accepted",
        ))

    facts_for_material: dict[str, list[PlannedFact]] = defaultdict(list)
    claims_for_material: dict[str, list[PlannedClaim]] = defaultdict(list)
    for fact in planned_facts:
        facts_for_material[fact.material_id].append(fact)
    for claim in planned_claims:
        claims_for_material[claim.material_id].append(claim)

    materials: list[PlannedMaterial] = []
    for page in material_keys:
        slide = slides[page]
        material_id = material_ids[page]
        page_facts = facts_for_material[material_id]
        page_claims = claims_for_material[material_id]
        brand_id = None if slide.brand == "ALL" else brand_mapping[slide.brand]
        entity = brands_by_id[brand_id].name if brand_id else None
        source_names = list(dict.fromkeys(fact.source for fact in page_facts))
        urls = [fact.url for fact in page_facts if fact.url]
        title = slide.headline.strip() or f"{baseline.manifest.title} · p.{page}"
        materials.append(PlannedMaterial(
            page=page,
            source_id=source_ids[page],
            material_id=material_id,
            brand_id=brand_id,
            entity=entity,
            section_id=SECTION_MAP.get(slide.section, "campaign"),
            title=title,
            source_title=f"{baseline.manifest.title} · p.{page}",
            source_url=urls[0] if urls else None,
            publisher="; ".join(source_names)[:200] or None,
            published_at=baseline.manifest.received_on.isoformat(),
            excerpt="\n".join(claim.text for claim in page_claims),
            fact_ids=[fact.fact_id for fact in page_facts],
            claim_ids=[claim.claim_id for claim in page_claims],
        ))

    return GoldenInputPlan(
        baseline_id=baseline.manifest.baseline_id,
        project_id=project_id,
        brand_mapping=brand_mapping,
        materials=materials,
        facts=planned_facts,
        claims=planned_claims,
        unsupported_facts=unsupported,
    )
