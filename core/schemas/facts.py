"""Fact / DerivedFact / Post / Finding contracts (PRD 8, 9)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

Confidence = Literal["verified", "estimated", "missing"]
# candidate: not yet usable. eligible: confirmed by a person (batch or card acceptance).
VerificationStatus = Literal["candidate", "eligible", "rejected"]

INPUT_METRICS = {
    # metric: (unit, required dims, optional dims)
    "search_group_sum": ("index", {"window", "seg", "scale_id"}, {"cat"}),
    "search_index_monthly": ("index", {"month", "seg", "scale_id"}, set()),
}

# Manually entered facts for case cards / market slides. Unit decides the formatter.
MANUAL_METRICS = {
    "views": "count",
    "likes": "count",
    "comments": "count",
    "followers": "count",
    "count": "count",
    "amount_krw": "krw",
    "percent": "percent",
    "rank": "rank",
}


class Fact(BaseModel):
    id: str
    content_hash: str
    brand_id: str
    entity: str
    metric: str
    value: Optional[Decimal]
    unit: str
    dims: dict[str, str] = Field(default_factory=dict)
    period_start: date
    period_end: date
    measured_at: date
    source: str
    source_id: Optional[str] = None
    evidence_id: Optional[str] = None
    url: Optional[str] = None
    method: Optional[str] = None
    confidence: Confidence
    verification_status: VerificationStatus = "candidate"
    source_record_key: Optional[str] = None
    source_locator: Optional[str] = None
    batch_id: Optional[str] = None
    row_no: Optional[int] = None
    label: Optional[str] = None  # human label for manual facts
    # Same natural key with different values from different sources: held until a person picks.
    conflict_key: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.verification_status == "eligible" and self.confidence != "missing" and self.value is not None


DerivedValue = Union[Decimal, int, str, bool, None]


class DerivedFact(BaseModel):
    id: str
    formula_id: str
    formula_version: str
    derived_from: list[str]
    parameters: dict[str, Any] = Field(default_factory=dict)
    brand_id: str
    entity: Optional[str] = None
    metric: str
    value: DerivedValue
    unit: str
    measured_at: Optional[date] = None
    observation_span: Optional[tuple[date, date]] = None
    confidence: Confidence = "verified"
    partial: bool = False  # e.g. ER with hidden likes (displayed with †)
    definition: Optional[str] = None


class Post(BaseModel):
    post_id: str
    brand_id: str
    channel: Literal["youtube", "instagram"]
    creator: str
    owner_type: Literal["self", "co", "creator"]
    posted_at: date
    measured_at: date
    followers: Optional[int] = None
    followers_measured_at: Optional[date] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    likes_hidden: bool = False
    product: Optional[str] = None
    url: Optional[str] = None
    row_no: Optional[int] = None
    batch_id: Optional[str] = None
    verification_status: VerificationStatus = "candidate"
    # field -> raw Fact id (source_locator = post_id:field)
    fact_ids: dict[str, str] = Field(default_factory=dict)

    @property
    def rate_basis(self) -> str:
        return "subscribers" if self.channel == "youtube" else "followers"

    def quarter(self) -> str:
        return f"Q{(self.posted_at.month - 1) // 3 + 1}"


class RowError(BaseModel):
    file: str
    row_no: int
    column: Optional[str] = None
    code: str
    message: str


class DuplicateRecord(BaseModel):
    kept_row: int
    dropped_row: int
    natural_key: str
    reason: str


class ImportResult(BaseModel):
    file: str
    batch_id: str
    facts: list[Fact] = Field(default_factory=list)
    posts: list[Post] = Field(default_factory=list)
    errors: list[RowError] = Field(default_factory=list)
    duplicates: list[DuplicateRecord] = Field(default_factory=list)
    total_rows: int = 0


class Finding(BaseModel):
    id: str
    rule_id: str
    brand_id: str
    strength: Decimal
    summary: dict[str, Any]
    fact_ids: list[str]
    rival: Optional[str] = None
    cat: Optional[str] = None
    # entities / windows that a slide must display for this finding to be cited (PRD 11)
    entities: list[str] = Field(default_factory=list)
    windows: list[str] = Field(default_factory=list)
    allowed_expression: str = ""
    review_status: Literal["pending", "accepted", "excluded", "stale"] = "pending"
    version: int = 1
