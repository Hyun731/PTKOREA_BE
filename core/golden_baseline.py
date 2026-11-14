"""Versioned, evidence-linked golden baseline contracts and validation."""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BASELINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
RECORD_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")

SourceRole = Literal["factbook", "requirements", "supporting"]
SourceType = Literal["internal_report", "public_api", "public_web", "direct_count", "derived", "customer_provided"]
Verification = Literal["customer_approved", "source_checked", "needs_review"]
ClaimKind = Literal["headline", "evidence", "insight", "conclusion", "recommendation"]
SlideSection = Literal["front", "brand", "market", "owned", "competitor", "summary", "end"]
LedgerStatus = Literal["pending", "complete", "not_applicable"]


class BaselineSourceFile(BaseModel):
    role: SourceRole
    filename: str = Field(min_length=1)
    sha256: str
    page_count: Optional[int] = Field(default=None, ge=1)

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256_RE.fullmatch(normalized):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return normalized


class BaselineManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    baseline_id: str
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    received_on: date
    effective_start: date
    effective_end: date
    brands: list[str] = Field(min_length=1)
    slide_count: int = Field(ge=1)
    source_files: list[BaselineSourceFile] = Field(min_length=1)

    @field_validator("baseline_id")
    @classmethod
    def _baseline_id(cls, value: str) -> str:
        normalized = value.strip()
        if not BASELINE_ID_RE.fullmatch(normalized):
            raise ValueError("baseline_id must use lowercase letters, digits, dots, underscores, or hyphens")
        return normalized

    @field_validator("brands")
    @classmethod
    def _brands(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("brands cannot contain blank values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("brands must be unique")
        return normalized

    @model_validator(mode="after")
    def _dates_and_sources(self) -> "BaselineManifest":
        if self.effective_start > self.effective_end:
            raise ValueError("effective_start cannot be after effective_end")
        hashes = [source.sha256 for source in self.source_files]
        if len(set(hashes)) != len(hashes):
            raise ValueError("source file hashes must be unique")
        factbooks = [source for source in self.source_files if source.role == "factbook"]
        if not factbooks:
            raise ValueError("source_files must include a factbook")
        page_counts = {source.page_count for source in factbooks if source.page_count is not None}
        if page_counts and page_counts != {self.slide_count}:
            raise ValueError("factbook page_count must match slide_count")
        return self


class BaselineSlide(BaseModel):
    baseline_id: str
    page: int = Field(ge=1)
    brand: str = Field(min_length=1)
    section: SlideSection
    slide_type: str = Field(min_length=1)
    headline: str = ""
    template_candidate: str = ""
    fact_status: LedgerStatus = "pending"
    claim_status: LedgerStatus = "pending"


class BaselineFact(BaseModel):
    baseline_id: str
    fact_id: str
    brand: str = Field(min_length=1)
    slide_page: int = Field(ge=1)
    metric: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(min_length=1)
    period_start: date
    period_end: date
    measured_on: date
    source_name: str = Field(min_length=1)
    source_type: SourceType
    source_url: Optional[str] = None
    calculation: Optional[str] = None
    evidence_page: int = Field(ge=1)
    verification: Verification

    @field_validator("fact_id")
    @classmethod
    def _fact_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not RECORD_ID_RE.fullmatch(normalized):
            raise ValueError("fact_id must start with a letter and use letters, digits, underscores, or hyphens")
        return normalized

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an http(s) URL")
        return normalized

    @field_validator("calculation")
    @classmethod
    def _calculation(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def _period_and_calculation(self) -> "BaselineFact":
        if self.period_start > self.period_end:
            raise ValueError("period_start cannot be after period_end")
        if self.source_type == "derived" and not self.calculation:
            raise ValueError("derived facts require calculation")
        return self


class BaselineClaim(BaseModel):
    baseline_id: str
    claim_id: str
    brand: str = Field(min_length=1)
    slide_page: int = Field(ge=1)
    kind: ClaimKind
    text: str = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_page: int = Field(ge=1)
    verification: Verification

    @field_validator("claim_id")
    @classmethod
    def _claim_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not RECORD_ID_RE.fullmatch(normalized):
            raise ValueError("claim_id must start with a letter and use letters, digits, underscores, or hyphens")
        return normalized

    @field_validator("fact_ids")
    @classmethod
    def _fact_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values if value.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("fact_ids cannot contain duplicates")
        invalid = [value for value in normalized if not RECORD_ID_RE.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid fact_ids: {', '.join(invalid)}")
        return normalized


class GoldenBaseline(BaseModel):
    manifest: BaselineManifest
    slides: list[BaselineSlide]
    facts: list[BaselineFact]
    claims: list[BaselineClaim]


class GoldenBaselineError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("\n".join(issues))


def _csv_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise GoldenBaselineError([f"{path.name}: missing header"])
        return [(row_no, {key: value or "" for key, value in row.items()}) for row_no, row in enumerate(reader, 2)]


def _load_csv(path: Path, model, *, fact_ids: bool = False) -> list:
    records = []
    issues = []
    for row_no, raw in _csv_rows(path):
        data = {key: value.strip() for key, value in raw.items()}
        if fact_ids:
            data["fact_ids"] = [value for value in data.get("fact_ids", "").split(";") if value.strip()]
        try:
            records.append(model.model_validate(data))
        except Exception as exc:
            issues.append(f"{path.name}:{row_no}: {exc}")
    if issues:
        raise GoldenBaselineError(issues)
    return records


def load_golden_baseline(directory: str | Path, *, strict: bool = False) -> GoldenBaseline:
    root = Path(directory)
    issues = []
    required = [root / "baseline.json", root / "slides.csv", root / "facts.csv", root / "claims.csv"]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise GoldenBaselineError([f"missing required file: {name}" for name in missing])
    try:
        manifest = BaselineManifest.model_validate(json.loads(required[0].read_text(encoding="utf-8")))
        slides = _load_csv(required[1], BaselineSlide)
        facts = _load_csv(required[2], BaselineFact)
        claims = _load_csv(required[3], BaselineClaim, fact_ids=True)
    except json.JSONDecodeError as exc:
        raise GoldenBaselineError([f"baseline.json: {exc}"]) from exc

    baseline_ids = {manifest.baseline_id}
    allowed_brands = set(manifest.brands) | {"ALL"}
    page_numbers = {slide.page for slide in slides}
    fact_ids = {fact.fact_id for fact in facts}
    facts_by_id = {fact.fact_id: fact for fact in facts}
    slides_by_page = {slide.page: slide for slide in slides}

    if len(page_numbers) != len(slides):
        issues.append("slides.csv: page values must be unique")
    expected_pages = set(range(1, manifest.slide_count + 1))
    if page_numbers != expected_pages:
        missing_pages = sorted(expected_pages - page_numbers)
        extra_pages = sorted(page_numbers - expected_pages)
        if missing_pages:
            issues.append(f"slides.csv: missing pages {missing_pages}")
        if extra_pages:
            issues.append(f"slides.csv: pages exceed slide_count {extra_pages}")
    if len(fact_ids) != len(facts):
        issues.append("facts.csv: fact_id values must be unique")
    claim_ids = {claim.claim_id for claim in claims}
    if len(claim_ids) != len(claims):
        issues.append("claims.csv: claim_id values must be unique")

    for kind, records in (("slides.csv", slides), ("facts.csv", facts), ("claims.csv", claims)):
        for record in records:
            if record.baseline_id not in baseline_ids:
                issues.append(f"{kind}: {getattr(record, 'page', getattr(record, 'slide_page', '?'))} uses another baseline_id")
            if record.brand not in allowed_brands:
                issues.append(f"{kind}: unknown brand {record.brand!r}")

    for fact in facts:
        if fact.slide_page not in page_numbers:
            issues.append(f"facts.csv: {fact.fact_id} references missing slide_page {fact.slide_page}")
        elif slides_by_page[fact.slide_page].brand not in {"ALL", fact.brand}:
            issues.append(f"facts.csv: {fact.fact_id} brand does not match slide_page {fact.slide_page}")
        if fact.evidence_page not in page_numbers:
            issues.append(f"facts.csv: {fact.fact_id} references missing evidence_page {fact.evidence_page}")
    for claim in claims:
        if claim.slide_page not in page_numbers:
            issues.append(f"claims.csv: {claim.claim_id} references missing slide_page {claim.slide_page}")
        elif slides_by_page[claim.slide_page].brand not in {"ALL", claim.brand}:
            issues.append(f"claims.csv: {claim.claim_id} brand does not match slide_page {claim.slide_page}")
        if claim.evidence_page not in page_numbers:
            issues.append(f"claims.csv: {claim.claim_id} references missing evidence_page {claim.evidence_page}")
        missing_facts = sorted(set(claim.fact_ids) - fact_ids)
        if missing_facts:
            issues.append(f"claims.csv: {claim.claim_id} references missing facts {missing_facts}")
        foreign_facts = sorted(fact_id for fact_id in claim.fact_ids
                               if fact_id in facts_by_id and facts_by_id[fact_id].brand not in {"ALL", claim.brand})
        if foreign_facts:
            issues.append(f"claims.csv: {claim.claim_id} references facts from another brand {foreign_facts}")

    if strict:
        pending_pages = [slide.page for slide in slides
                         if slide.fact_status == "pending" or slide.claim_status == "pending"]
        if pending_pages:
            issues.append(f"strict validation: incomplete slide ledgers {pending_pages}")
        if not facts:
            issues.append("strict validation: facts.csv has no records")
        if not claims:
            issues.append("strict validation: claims.csv has no records")
        pending = [record_id for record_id, verification in [
            *((fact.fact_id, fact.verification) for fact in facts),
            *((claim.claim_id, claim.verification) for claim in claims),
        ] if verification == "needs_review"]
        if pending:
            issues.append(f"strict validation: needs_review records {pending}")

    if issues:
        raise GoldenBaselineError(issues)
    return GoldenBaseline(manifest=manifest, slides=slides, facts=facts, claims=claims)
