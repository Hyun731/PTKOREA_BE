"""Phase 1-4: 브랜드 × 채널별 수집 현황 — 기사(언론)에만 치우쳤는지 기획자가 바로 알 수 있게.

채널별 '수집 부족' 기준(핸드오프 §Phase 1-4):
- 공식 채널: 확인된(채택된) 공식 계정 전부가 최근 6개월 안에 수집됐는지
- 인플루언서: 게시물 10건 이상
- 카페·블로그: 20건 이상
- 커뮤니티: 20건 이상, 서로 다른 3곳 이상
- 리뷰: 2개 플랫폼 이상, 원문 30건 이상(Phase 2 — 플랫폼 공개 리뷰 수, 제외되지 않은 스냅샷만)
언론은 최소 건수 대신 전체에서 차지하는 비율로 본다 — 40%를 넘으면 경고.
전자·뷰티·패션처럼 리뷰가 필수인 업종은 소비자 원문(카페·블로그+커뮤니티+리뷰) 중 리뷰 비중이
50% 미만이면 커뮤니티·카페만으로 채운 것으로 보고 따로 경고한다(핸드오프 Phase 2 §5).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FactRow, Material, PostRow, Project, ReviewSnapshot, Source
from core.schemas.project import REQUIRED_REVIEW_INDUSTRIES, Project as CoreProject

PRESS_WARN_RATIO = 0.4
RECENT_DAYS = 183  # ~6 months
INFLUENCER_MIN = 10
VOC_MIN = 20
COMMUNITY_SITES_MIN = 3
REVIEW_MIN = 30
REVIEW_PLATFORMS_MIN = 2
REVIEW_SHARE_MIN = 0.5  # 리뷰 필수 업종: 소비자 원문 중 리뷰 비중 최소치
CHANNEL_LABEL = {"press": "언론", "owned": "공식 채널", "influencer": "SNS·인플루언서",
                 "cafe_blog": "카페·블로그", "community": "커뮤니티", "kin": "지식iN", "sns_search": "SNS 검색",
                 "review": "리뷰"}
# P2-8: 소비자 원문 중 지식iN과 SNS 검색(X·Threads·TikTok·YouTube 댓글)은 최소 건수 없이 건수만 보인다.
EXTRA_VOC_HOSTS = {"kin.naver.com": "kin", "x.com": "sns_search", "twitter.com": "sns_search",
                   "threads.com": "sns_search", "threads.net": "sns_search", "tiktok.com": "sns_search",
                   "youtube.com": "sns_search", "youtu.be": "sns_search"}


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


def _voc(db: Session, project_id: str, brand_id: str, entity: str) -> dict:
    from app.services.research import VOC_SITE_CHANNEL, _host

    rows = db.execute(select(Material, Source).join(Source, Source.id == Material.source_id).where(
        Material.project_id == project_id, Material.brand_id == brand_id, Material.entity == entity,
        Material.section_id == "voc", Material.duplicate_of.is_(None))).all()
    counts = {"cafe_blog": 0, "community": 0, "kin": 0, "sns_search": 0}
    sites: dict[str, set[str]] = {"cafe_blog": set(), "community": set()}
    for _, s in rows:
        host = _host(s.original_url or "")
        channel = next((c for site, c in {**VOC_SITE_CHANNEL, **EXTRA_VOC_HOSTS}.items()
                        if host == site or host.endswith(f".{site}")), None)
        if channel:
            counts[channel] += 1
            sites.setdefault(channel, set()).add(host)
    cafe_blog = {"count": counts["cafe_blog"], "min": VOC_MIN, "enough": counts["cafe_blog"] >= VOC_MIN,
                "action": "조사 계획에서 소비자 원문 항목을 다시 모으세요"}
    community = {"count": counts["community"], "min": VOC_MIN, "sites": len(sites["community"]),
                "sites_min": COMMUNITY_SITES_MIN,
                "enough": counts["community"] >= VOC_MIN and len(sites["community"]) >= COMMUNITY_SITES_MIN,
                "action": "조사 계획에서 소비자 원문 항목을 다시 모으세요"}
    return {"cafe_blog": cafe_blog, "community": community, "kin": {"count": counts["kin"]},
            "sns_search": {"count": counts["sns_search"]}}


def _review(snapshots: list[ReviewSnapshot], brand_id: str, entity: str) -> dict:
    rows = [s for s in snapshots if s.brand_id == brand_id and s.entity == entity
           and s.review_status != "excluded" and s.access_status == "ok"]
    count = sum(s.review_count or 0 for s in rows)
    platforms = len({s.platform for s in rows})
    return {"count": count, "min": REVIEW_MIN, "platforms": platforms, "platforms_min": REVIEW_PLATFORMS_MIN,
           "enough": count >= REVIEW_MIN and platforms >= REVIEW_PLATFORMS_MIN,
           "action": "조사 계획에서 커머스 리뷰 항목을 다시 모으세요"}


def _access_unavailable(db: Session, project_id: str, brand_id: str) -> int:
    rows = db.scalars(select(Source.id).join(Material, Material.source_id == Source.id).where(
        Material.project_id == project_id, Material.brand_id == brand_id, Source.access_status == "unavailable"))
    return len(list(rows))


def compute(db: Session, project: Project) -> list[dict]:
    core = CoreProject.model_validate(project.config)
    materials = list(db.scalars(select(Material).where(Material.project_id == project.id)))
    facts = list(db.scalars(select(FactRow).where(FactRow.project_id == project.id)))
    posts = list(db.scalars(select(PostRow).where(PostRow.project_id == project.id)))
    snapshots = list(db.scalars(select(ReviewSnapshot).where(ReviewSnapshot.project_id == project.id)))

    out = []
    for b in core.brands:
        press = {"count": _press(materials, b.id), "label": CHANNEL_LABEL["press"]}
        owned = {**_owned(facts, b, b.id), "label": CHANNEL_LABEL["owned"]}
        influencer = {**_influencer(posts, b.id), "label": CHANNEL_LABEL["influencer"]}
        voc = _voc(db, project.id, b.id, b.name)
        review = {**_review(snapshots, b.id, b.name), "label": CHANNEL_LABEL["review"]}
        channels = {"press": press, "owned": owned, "influencer": influencer,
                   "cafe_blog": {**voc["cafe_blog"], "label": CHANNEL_LABEL["cafe_blog"]},
                   "community": {**voc["community"], "label": CHANNEL_LABEL["community"]},
                   "kin": {**voc["kin"], "label": CHANNEL_LABEL["kin"]},
                   "sns_search": {**voc["sns_search"], "label": CHANNEL_LABEL["sns_search"]}, "review": review}
        total = sum(c["count"] for c in channels.values())
        press_ratio = round(press["count"] / total, 3) if total else 0.0
        # 리뷰 필수 업종: 소비자 원문(카페·블로그+커뮤니티+리뷰) 중 리뷰 비중이 낮으면 커뮤니티만으로
        # 채운 것 — 업종 KPI(3-10)와 같은 기준의 REQUIRED_REVIEW_INDUSTRIES를 그대로 쓴다.
        consumer_total = sum(channels[c]["count"] for c in ("cafe_blog", "community", "kin", "sns_search")) + review["count"]
        review_share = round(review["count"] / consumer_total, 3) if consumer_total else 0.0
        review_required = b.industry in REQUIRED_REVIEW_INDUSTRIES
        out.append({
            "brand_id": b.id, "brand_name": b.name, "channels": channels,
            "access_unavailable": _access_unavailable(db, project.id, b.id),
            "press_ratio": press_ratio, "press_over_warning": press_ratio > PRESS_WARN_RATIO and total > 0,
            "review_share": review_share,
            "review_share_warning": review_required and consumer_total > 0 and review_share < REVIEW_SHARE_MIN,
        })
    return out
