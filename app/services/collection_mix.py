"""Phase 1-4: 브랜드 × 채널별 수집 현황 — 기사(언론)에만 치우쳤는지 기획자가 바로 알 수 있게.

채널별 '수집 부족' 기준(핸드오프 §Phase 1-4):
- 공식 채널: 확인된(채택된) 공식 계정 전부가 최근 6개월 안에 수집됐는지
- 인플루언서: 게시물 10건 이상
- 카페·블로그: 20건 이상 (아직 수집기가 없어 Phase 1-3 전에는 항상 0건)
- 커뮤니티: 20건 이상, 서로 다른 3곳 이상 (위와 같은 이유로 항상 0건)
- 리뷰: 2개 플랫폼 이상, 원문 30건 이상 (Phase 2 전에는 항상 0건)
언론은 최소 건수 대신 전체에서 차지하는 비율로 본다 — 40%를 넘으면 경고.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FactRow, Material, PostRow, Project, Source
from core.schemas.project import Project as CoreProject

PRESS_WARN_RATIO = 0.4
RECENT_DAYS = 183  # ~6 months
INFLUENCER_MIN = 10
# Not implemented yet (Phase 1-3 / Phase 2): always 0, shown so the gap is visible, not hidden.
NOT_IMPLEMENTED = ("cafe_blog", "community", "review")
CHANNEL_LABEL = {"press": "언론", "owned": "공식 채널", "influencer": "SNS·인플루언서",
                 "cafe_blog": "카페·블로그", "community": "커뮤니티", "review": "리뷰"}


def _press(materials: list[Material], brand_id: str) -> int:
    # Several outlets covering one activity count once (dedupe.py already merged them).
    return sum(1 for m in materials if m.brand_id == brand_id and m.section_id in ("campaign", "market")
              and m.duplicate_of is None and m.review_status != "excluded")


def _owned(facts: list[FactRow], core_brand, brand_id: str) -> dict:
    confirmed = [p.channel for p in core_brand.official_profiles if p.status == "confirmed"]
    if not confirmed:
        return {"count": 0, "total": 0, "enough": False, "action": "설정에서 공식 계정을 등록하거나 후보를 확인하세요"}
    cutoff = date.today() - timedelta(days=RECENT_DAYS)
    recent_channels: set[str] = set()
    for f in facts:
        d = f.data
        if d.get("brand_id") != brand_id or d.get("entity") != core_brand.name or not str(d.get("metric", "")).startswith("owned_"):
            continue
        measured = d.get("measured_at")
        if measured and str(measured) >= cutoff.isoformat():
            recent_channels.add((d.get("dims") or {}).get("channel", ""))
    count = len(recent_channels & set(confirmed))
    return {"count": count, "total": len(confirmed), "enough": count >= len(confirmed),
           "action": "자료 확인에서 '다시 모으기'로 최근 자료를 받으세요"}


def _influencer(posts: list[PostRow], brand_id: str) -> dict:
    count = sum(1 for p in posts if p.data.get("brand_id") == brand_id and p.data.get("owner_type") == "creator")
    return {"count": count, "min": INFLUENCER_MIN, "enough": count >= INFLUENCER_MIN,
           "action": "조사 계획에서 인플루언서 항목을 다시 모으세요"}


def _access_unavailable(db: Session, project_id: str, brand_id: str) -> int:
    rows = db.scalars(select(Source.id).join(Material, Material.source_id == Source.id).where(
        Material.project_id == project_id, Material.brand_id == brand_id, Source.access_status == "unavailable"))
    return len(list(rows))


def compute(db: Session, project: Project) -> list[dict]:
    core = CoreProject.model_validate(project.config)
    materials = list(db.scalars(select(Material).where(Material.project_id == project.id)))
    facts = list(db.scalars(select(FactRow).where(FactRow.project_id == project.id)))
    posts = list(db.scalars(select(PostRow).where(PostRow.project_id == project.id)))

    out = []
    for b in core.brands:
        press = {"count": _press(materials, b.id), "label": CHANNEL_LABEL["press"]}
        owned = {**_owned(facts, b, b.id), "label": CHANNEL_LABEL["owned"]}
        influencer = {**_influencer(posts, b.id), "label": CHANNEL_LABEL["influencer"]}
        not_ready = {c: {"count": 0, "label": CHANNEL_LABEL[c], "enough": False, "not_implemented": True}
                    for c in NOT_IMPLEMENTED}
        channels = {"press": press, "owned": owned, "influencer": influencer, **not_ready}
        total = sum(c["count"] for c in channels.values())
        press_ratio = round(press["count"] / total, 3) if total else 0.0
        out.append({
            "brand_id": b.id, "brand_name": b.name, "channels": channels,
            "access_unavailable": _access_unavailable(db, project.id, b.id),
            "press_ratio": press_ratio, "press_over_warning": press_ratio > PRESS_WARN_RATIO and total > 0,
        })
    return out
