"""Persistence model (PRD 8 데이터 계약). Originals are never overwritten: corrections
create new rows/versions and the change is written to the audit log."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON)  # core.schemas.project.Project dump
    version: Mapped[int] = mapped_column(Integer, default=1)
    omitted_slots: Mapped[dict] = mapped_column(JSON, default=dict)  # slot_id -> {reason, by, at}
    lead_overrides: Mapped[dict] = mapped_column(JSON, default=dict)  # slide_id -> [Paragraph]
    owner: Mapped[str] = mapped_column(String(120), default="dev")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResearchPlan(Base):
    __tablename__ = "research_plans"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    project_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchItem(Base):
    __tablename__ = "research_items"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("research_plans.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str] = mapped_column(String(10))
    entity: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))  # self | competitor | benchmark | market
    section_id: Mapped[str] = mapped_column(String(40))
    scope_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 조사 범위 항목 (app.services.scope)
    question: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    # Job state set: not_started | queued | running | succeeded | partial | failed | cancelled | blocked_budget | needs_review
    execution_status: Mapped[str] = mapped_column(String(20), default="not_started")
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|excluded|stale
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    omission_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latest_job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"post_urls": [...]} chosen by a person
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)  # per-item outcome of the latest run


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # facts | posts
    filename: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|accepted|rejected|replaced
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    duplicates: Mapped[list] = mapped_column(JSON, default=list)
    file_key: Mapped[str] = mapped_column(String(300))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("project_id", "batch_id", "fact_id"),)
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    fact_id: Mapped[str] = mapped_column(String(40), index=True)
    origin: Mapped[str] = mapped_column(String(10))  # csv | posts | manual | auto (AI-extracted candidate)
    batch_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    material_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    research_item_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)  # core Fact dump (value as string)
    verification_status: Mapped[str] = mapped_column(String(20), default="candidate")
    superseded_by: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PostRow(Base):
    __tablename__ = "posts"
    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(String(40), index=True)
    post_id: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    original_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upload_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    published_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="web")
    access_status: Mapped[str] = mapped_column(String(20), default="unknown")
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # page text as fetched: grounds summary, sentences, chat
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Material(Base):
    """Evidence card: a source + why it matters for which brand/section (PRD 7 자료 카드)."""
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    research_item_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    brand_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    entity: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    section_id: Mapped[str] = mapped_column(String(40), default="campaign")
    title: Mapped[str] = mapped_column(String(300))
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    activity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    activity_date_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")  # planner intent / hypothesis, never a fact
    excerpt: Mapped[str] = mapped_column(Text, default="")
    input_path: Mapped[str] = mapped_column(String(10), default="manual")
    review_status: Mapped[str] = mapped_column(String(20), default="candidate")
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    selected_asset_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # Another article about the same activity: kept as an extra source under the primary card, never its own slide.
    duplicate_of: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    duplicate_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    event_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # AI's short name for the activity
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 해석 요약: what was done, why, how it landed
    target_segment: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # one of core.schemas.materials.TARGET_SEGMENTS
    # P4 사례 카드 해설 (06_AI_프롬프트_템플릿.md): set only once a CaseCommentary proposal is accepted.
    ai_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_implication: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Person-picked for a one-slide deep dive (full image + period + numbered insights) instead of the card grid.
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("materials.id"), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    original_key: Mapped[str] = mapped_column(String(300))
    derived_key: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(40))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    crop: Mapped[dict] = mapped_column(JSON, default=lambda: {"x": 0, "y": 0, "w": 1, "h": 1})
    crop_history: Mapped[list] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    usage_basis: Mapped[str] = mapped_column(String(20), default="user_provided")
    review_status: Mapped[str] = mapped_column(String(20), default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[Optional[str]] = mapped_column(ForeignKey("materials.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # fact | interpretation | recommendation
    parts: Mapped[list] = mapped_column(JSON)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(10), default="user")
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    stale_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # verbatim source excerpt (AI candidates)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderCall(Base):
    """Usage ledger: every paid call is reserved before it starts and settled after (PRD 13)."""
    __tablename__ = "provider_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(30))
    endpoint: Mapped[str] = mapped_column(String(60))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20))  # reserved | settled | failed | cache_hit | unknown
    est_cost_usd: Mapped[float] = mapped_column(default=0.0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    cost_is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderCache(Base):
    """Provider responses keyed by provider + endpoint + normalized request + schema version."""
    __tablename__ = "provider_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    data: Mapped[Any] = mapped_column(JSON)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeadProposal(Base):
    """AI lead sentence candidate for one slide. Never overwrites a person's text until accepted."""
    __tablename__ = "lead_proposals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    slide_id: Mapped[str] = mapped_column(String(60))
    slide_title: Mapped[str] = mapped_column(String(200), default="")
    current: Mapped[list] = mapped_column(JSON, default=list)  # lead paragraphs at proposal time
    parts: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseCommentary(Base):
    """P4 사례 카드 해설 candidate for one competitor/benchmark case Material. Never overwrites a
    person's card until accepted (same pattern as LeadProposal)."""
    __tablename__ = "case_commentary"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    implication: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected|failed|superseded
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OwnedPost(Base):
    """A brand's own top-performing Instagram post (2-4 브랜드별 상위 게시물) — the richer
    per-post record that owned_posts_by_month's plain Fact counts can't carry (image, URL,
    per-post likes). Unlike a campaign Material this never needs a human-written comment or
    claim text; its image goes through the same Asset review gate everything else does."""
    __tablename__ = "owned_posts"
    __table_args__ = (UniqueConstraint("project_id", "channel", "post_id"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[str] = mapped_column(String(10), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # instagram (youtube: 2-5, not this slide)
    post_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    posted_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    asset_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    research_item_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deck(Base):
    __tablename__ = "decks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="building")  # building|ready|failed
    spec: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    qc: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pptx_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    preview_keys: Mapped[list] = mapped_column(JSON, default=list)
    render_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ok|unavailable|failed
    render_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Editor copy: the generated `spec` stays as built; edits live here until reset.
    edit_slides: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    edit_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    edit_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class EditLog(Base):
    """Editor history: every AI edit request (proposed → applied / cancelled), restores and resets.
    Applied rows keep the slides just before and just after, so any of them can be gone back to."""
    __tablename__ = "edit_logs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[str] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ai | restore | reset
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | applied | cancelled
    message: Mapped[str] = mapped_column(Text, default="")
    reply: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    slide_ids: Mapped[list] = mapped_column(JSON, default=list)  # slides the change touched
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # applied / rejected command summaries
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    actor: Mapped[str] = mapped_column(String(120), default="")
    slides_before: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    slides_after: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    edit_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # editor copy version it produced
    restored_from: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    deck_id: Mapped[str] = mapped_column(ForeignKey("decks.id"))
    deck_version: Mapped[int] = mapped_column(Integer)
    qc: Mapped[dict] = mapped_column(JSON)
    manifest: Mapped[dict] = mapped_column(JSON)  # file name -> storage key
    edit_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # set when exported from the editor copy
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    project_version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(30))
    # queued | running | succeeded | partial | failed | cancelled | blocked_budget | needs_review
    state: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_run_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(120), default="dev")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
