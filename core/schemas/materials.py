"""Source / Evidence / Asset / Claim snapshots passed from storage into composition (PRD 7, 8).

The API owns persistence; composition only ever sees accepted, versioned snapshots.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.schemas.slidespec import Crop, Part

ReviewStatus = Literal["candidate", "accepted", "excluded"]

# 1-6 타겟·채널별 캠페인 매트릭스의 고정 행 (02_보고서_표준목차_장표명세.md §1-6). AI 추출이나 사람이
# 자료 카드에 다는 분류 태그 — 추측이 아니라 원문에 실제로 드러난 타겟일 때만 붙는다.
TARGET_SEGMENTS: tuple[str, ...] = (
    "대학생·Gen Z", "20~30대", "직장인", "30~40대·가족", "외국인 관광객", "팝업·OOH·PR",
)


class SourceRef(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    upload_key: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[date] = None
    fetched_at: Optional[datetime] = None
    source_type: Literal["web", "social", "upload", "csv", "synthetic", "report"] = "web"
    access_status: Literal["ok", "unavailable", "unknown"] = "unknown"


class AssetRef(BaseModel):
    id: str
    version: int = 1
    source_id: Optional[str] = None
    path: str  # normalized derivative file (original kept separately)
    width: int
    height: int
    crop: Crop = Field(default_factory=Crop)
    title: str = ""
    description: str = ""
    usage_basis: Literal["user_provided", "source_reference", "licensed"] = "user_provided"
    review_status: ReviewStatus = "candidate"
    sha256: str = ""


class ClaimRef(BaseModel):
    id: str
    kind: Literal["fact", "interpretation", "recommendation"]
    parts: list[Part]
    evidence_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    review_status: Literal["pending", "accepted", "excluded", "stale"] = "pending"
    author: Literal["user", "ai", "rule"] = "user"
    quote: Optional[str] = None  # verbatim source sentence the claim rests on (AI candidates)


class OwnedPostRef(BaseModel):
    """2-4 브랜드별 상위 게시물 — a channel-inventory post, not a campaign case Material."""
    id: str
    brand_id: str
    channel: str
    url: Optional[str] = None
    posted_at: Optional[date] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    asset: Optional[AssetRef] = None


class CaseMaterial(BaseModel):
    """An evidence card used for C1/M1 slides."""
    id: str
    brand_id: Optional[str] = None
    entity: Optional[str] = None  # brand / competitor / benchmark name shown on the card
    section_id: str = "campaign"
    title: str
    label: Optional[str] = None
    event_name: Optional[str] = None  # short activity name from AI extraction, used for the card header
    source: SourceRef
    activity_date: Optional[date] = None
    activity_date_end: Optional[date] = None
    asset: Optional[AssetRef] = None
    metric_fact_ids: list[str] = Field(default_factory=list)
    claims: list[ClaimRef] = Field(default_factory=list)
    comment: str = ""
    review_status: ReviewStatus = "candidate"
    input_path: Literal["auto", "manual"] = "manual"
    # Person-picked for a one-slide deep dive instead of the card grid (PRD 11 case_spotlight).
    featured: bool = False
    order: int = 0
    target_segment: Optional[str] = None  # one of TARGET_SEGMENTS, or None if not evident in the source
    ai_detail: Optional[str] = None  # P4 사례 카드 해설: 무엇을 했고 왜 통했나 (accepted CaseCommentary only)
    ai_implication: Optional[str] = None  # P4: 자사에 적용할 시사점
