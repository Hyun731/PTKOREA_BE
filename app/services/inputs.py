"""Load the accepted, versioned snapshot a deck build depends on (PRD 8 공통 원칙)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, Claim, FactRow, ImportBatch, Material, OwnedPost, PostRow, Project, ResearchItem, ReviewKeyword,
    ReviewSnapshot, SlideWriting, Source, SynthesisRun,
)
from app.storage import get_storage
from core.composition.build import BuildInputs
from core.schemas.facts import Fact, Post
from core.schemas.materials import (
    AssetRef, CaseMaterial, ClaimRef, OwnedPostRef, ReviewKeywordRef, ReviewSnapshotRef, SourceRef,
)
from core.schemas.project import Project as CoreProject
from core.schemas.slidespec import Crop, Headline, Part


def core_project(p: Project) -> CoreProject:
    return CoreProject.model_validate(p.config)


def source_ref(s: Source) -> SourceRef:
    return SourceRef(id=s.id, title=s.title, url=s.original_url, upload_key=s.upload_key, publisher=s.publisher,
                     published_at=s.published_at, fetched_at=s.fetched_at, source_type=s.source_type,
                     access_status=s.access_status)


def asset_ref(a: Asset) -> AssetRef:
    return AssetRef(id=a.id, version=a.version, source_id=a.source_id, path=str(get_storage().path(a.derived_key)),
                    width=a.width, height=a.height, crop=Crop(**a.crop), title=a.title, description=a.description,
                    usage_basis=a.usage_basis, review_status=a.review_status, sha256=a.sha256)


def claim_ref(c: Claim) -> ClaimRef:
    return ClaimRef(id=c.id, kind=c.kind, parts=[Part(**p) for p in c.parts], evidence_ids=c.evidence_ids,
                    fact_ids=c.fact_ids, review_status=c.review_status, author=c.author, quote=c.quote)


def slide_writings(db: Session, project_id: str) -> dict:
    """AI writing made at build time, {kind: {slide_id: {"fp": body fingerprint, **data}}} (P3-4~)."""
    out: dict[str, dict] = {}
    for w in db.scalars(select(SlideWriting).where(SlideWriting.project_id == project_id, SlideWriting.status == "ok")
                        .order_by(SlideWriting.slide_id, SlideWriting.kind)):
        out.setdefault(w.kind, {})[w.slide_id] = {"fp": w.body_fp, **(w.data or {})}
    return out


def load_inputs(db: Session, project: Project) -> BuildInputs:
    accepted_batches = {b.id for b in db.scalars(select(ImportBatch).where(
        ImportBatch.project_id == project.id, ImportBatch.status == "accepted"))}
    by_id: dict[str, Fact] = {}
    for row in db.scalars(select(FactRow).where(FactRow.project_id == project.id, FactRow.superseded_by.is_(None))):
        f = Fact.model_validate(row.data)
        if row.origin in ("csv", "posts"):
            status = "eligible" if row.batch_id in accepted_batches else "candidate"
        else:
            status = row.verification_status
        # The same content-hash Fact can arrive in several batches; eligible wins.
        if f.id not in by_id or status == "eligible":
            by_id[f.id] = f.model_copy(update={"verification_status": status})
    facts: list[Fact] = list(by_id.values())
    posts: list[Post] = []
    for row in db.scalars(select(PostRow).where(PostRow.project_id == project.id)):
        p = Post.model_validate(row.data)
        posts.append(p.model_copy(update={"verification_status": "eligible" if row.batch_id in accepted_batches else "candidate"}))

    materials: list[CaseMaterial] = []
    mats = list(db.scalars(select(Material).where(Material.project_id == project.id, Material.duplicate_of.is_(None))
                           .order_by(Material.order, Material.created_at)))
    sources = {s.id: s for s in db.scalars(select(Source).where(Source.project_id == project.id))}
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.project_id == project.id))}
    claims_by_mat: dict[str, list[Claim]] = {}
    for c in db.scalars(select(Claim).where(Claim.project_id == project.id)):
        if c.material_id:
            claims_by_mat.setdefault(c.material_id, []).append(c)
    manual_by_mat: dict[str, list[str]] = {}
    for row in db.scalars(select(FactRow).where(FactRow.project_id == project.id, FactRow.origin.in_(("manual", "auto")),
                                                FactRow.superseded_by.is_(None))):
        if row.material_id:
            manual_by_mat.setdefault(row.material_id, []).append(row.fact_id)
    for m in mats:
        asset = assets.get(m.selected_asset_id) if m.selected_asset_id else None
        materials.append(CaseMaterial(
            id=m.id, brand_id=m.brand_id, entity=m.entity, section_id=m.section_id, title=m.title, label=m.label, event_name=m.event_name,
            source=source_ref(sources[m.source_id]), activity_date=m.activity_date, activity_date_end=m.activity_date_end,
            asset=asset_ref(asset) if asset else None, metric_fact_ids=manual_by_mat.get(m.id, []),
            claims=[claim_ref(c) for c in sorted(claims_by_mat.get(m.id, []), key=lambda c: c.created_at)],
            comment=m.comment, review_status=m.review_status, input_path=m.input_path, featured=m.featured, order=m.order,
            target_segment=m.target_segment, ai_detail=m.ai_detail, ai_implication=m.ai_implication,
            voc_sentiment=m.voc_sentiment, voc_topic=m.voc_topic, voc_awareness=m.voc_awareness,
            voc_sponsored=m.voc_sponsored, market_aspect=m.market_aspect,
            related_brand_ids=m.related_brand_ids or []))
    owned_posts: list[OwnedPostRef] = []
    for op in db.scalars(select(OwnedPost).where(OwnedPost.project_id == project.id).order_by(OwnedPost.likes.desc())):
        asset = assets.get(op.asset_id) if op.asset_id else None
        owned_posts.append(OwnedPostRef(id=op.id, brand_id=op.brand_id, entity=op.entity, channel=op.channel,
                                        url=op.url, posted_at=op.posted_at, likes=op.likes, comments=op.comments,
                                        views=op.views, comment_sentiment=op.comment_sentiment,
                                        asset=asset_ref(asset) if asset else None))

    # Phase 2 커머스 리뷰: 스냅샷·키워드 모두 싣고(채택 여부 무관), composition이 accepted만 골라 쓴다.
    reviews: list[ReviewSnapshotRef] = []
    snaps = list(db.scalars(select(ReviewSnapshot).where(ReviewSnapshot.project_id == project.id)))
    kws_by_snap: dict[str, list[ReviewKeyword]] = {}
    if snaps:
        for k in db.scalars(select(ReviewKeyword).where(ReviewKeyword.snapshot_id.in_([s.id for s in snaps]))):
            kws_by_snap.setdefault(k.snapshot_id, []).append(k)
    for s in snaps:
        reviews.append(ReviewSnapshotRef(
            id=s.id, brand_id=s.brand_id, entity=s.entity, role=s.role, platform=s.platform,
            product_name=s.product_name, product_url=s.product_url, access_status=s.access_status, reason=s.reason,
            rating=s.rating, rating_scale=s.rating_scale, review_count=s.review_count,
            sponsored_count=s.sponsored_count, measured_at=s.measured_at, review_status=s.review_status,
            keywords=[ReviewKeywordRef(id=k.id, sentiment=k.sentiment, keyword=k.keyword, sample_size=k.sample_size,
                                       method=k.method, quotes=k.quotes, blocks_purchase=k.blocks_purchase,
                                       review_status=k.review_status) for k in kws_by_snap.get(s.id, [])]))

    omitted = {k: v["reason"] for k, v in (project.omitted_slots or {}).items()}
    # Saved before P3-4: a list of claim paragraphs (kept as a list so older decks keep their fingerprint).
    leads = {k: (Headline.coerce(v).claim if isinstance(v, list) else Headline.coerce(v))
             for k, v in (project.lead_overrides or {}).items()}
    ai_writing = slide_writings(db, project.id)
    synthesis: dict[str, dict] = {}
    for run in db.scalars(select(SynthesisRun).where(SynthesisRun.project_id == project.id, SynthesisRun.active.is_(True))):
        synthesis[run.brand_id] = run.data
    # Phase 3-4: Google Trends 연관 검색어 — 그 브랜드의 가장 최근 수집 결과만 쓴다.
    trend_related: dict[str, list[str]] = {}
    for ri in db.scalars(select(ResearchItem).where(ResearchItem.project_id == project.id,
                                                     ResearchItem.section_id == "search_trend")):
        queries = (ri.last_result or {}).get("related_queries") or []
        if queries:
            trend_related[ri.brand_id] = queries
    return BuildInputs(project=core_project(project), facts=facts, posts=posts, materials=materials,
                       owned_posts=owned_posts, omitted_slots=omitted, lead_overrides=leads, ai_writing=ai_writing, synthesis=synthesis,
                       trend_related=trend_related, reviews=reviews, generated_on=date.today(),
                       deck_id=project.id)
