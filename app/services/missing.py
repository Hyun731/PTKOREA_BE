"""Why a planned slide has no page yet, and what fixes it (팩트북 출력 · 초안 흐름).

A missing slide reads as "자료 없음" either way, but the fix differs: cards waiting to be adopted,
a search that found nothing, a setting the collector needs, or a CSV only a person can upload.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FactRow, Material, Project, ResearchItem, ResearchPlan, ReviewSnapshot, Source
from core.schemas.project import Project as CoreProject
from core.schemas.slidespec import SlotPlan

# cause -> (badge, what to do)
CAUSES = {
    "adopt": ("채택 대기", "모은 자료가 있습니다 — 자료 확인에서 채택하세요"),
    "collect": ("수집 필요", "아직 모은 자료가 없습니다 — 다시 모으기로 수집하세요"),
    "setup": ("설정 필요", "수집에 필요한 입력이 없습니다"),
    "upload": ("업로드 필요", "자동 수집이 없는 자료입니다 — CSV를 올리세요"),
    "access": ("접근 불가", "찾은 글에 접근할 수 없었습니다"),
}
# Slot template -> the research section that feeds it.
SECTION = {"1-6": "campaign", "C1": "campaign", "C2": "campaign", "M1": "market", "M2": "market_kpi",
           "3-1": "influencer", "2-1": "owned", "2-2": "owned", "2-4": "owned", "2-5": "owned",
           "5-1": "voc", "5-2": "voc", "TR1": "search_trend", "CM1": "commerce_review", "CM2": "commerce_review",
           "2-8a": "search", "2-8b": "search", "2-8c": "search", "2-8d": "search", "OW-CMP": "owned"}
# P3 비교·차트 장: 자료 카드가 아니라 자동 수집 수치(Fact)로 채워지므로, 확인 전 수치가 있으면 '채택 대기'.
FACT_METRICS: dict[str, tuple[str, ...]] = {
    "OW-CMP": ("owned_followers", "owned_posts_monthly", "owned_videos_monthly", "owned_likes_median",
               "owned_reactions_median", "owned_comments_median", "owned_views_avg", "owned_views_median"),
}
UPLOAD: set[str] = set()  # 검색 점유(2-8a~d)는 네이버 데이터랩으로 자동 수집한다(P2-1) — 업로드 전용 장표 없음


def _search_setup(slot: SlotPlan, brands: list, related: list) -> Optional[str]:
    """검색 장표가 설정 때문에 비어 있으면 무엇을 고칠지(없으면 None)."""
    from app.config import settings
    from core.ingestion.search_index import naver_target_filter

    if not settings.provider_configured("naver"):
        return "네이버 데이터랩 키(NAVER_API_HUB_CLIENT_ID/SECRET)가 서버에 설정되어 있지 않습니다 — 관리자에게 요청하세요"
    auth = next((e.get("message") for i in related for e in (i.last_result or {}).get("errors", [])
                 if e.get("code") == "PROVIDER_AUTH"), None)
    if auth:
        return auth
    if slot.template_id == "2-8c" and not any(b.categories for b in brands):
        return "설정에서 브랜드의 주력 카테고리를 넣으세요 — '브랜드+카테고리' 검색어를 만들 때 씁니다"
    if slot.template_id == "2-8d" and not any(
            b.target and naver_target_filter(b.target.age_min, b.target.age_max, b.target.gender) for b in brands):
        return "설정에서 키 타겟의 연령이나 성별을 넣으세요 — 타겟 검색 점유를 따로 잽니다"
    return None


def _case_role(slot: SlotPlan) -> Optional[str]:
    if slot.template_id not in ("C1", "C2"):
        return None
    head = slot.slot_id.split("-")[0]
    return {"C1c": "competitor", "C2c": "competitor", "C1b": "benchmark", "C2b": "benchmark"}.get(head, "self")


def annotate(db: Session, project: Project, core: CoreProject, plan: list[SlotPlan]) -> None:
    """Set `cause`, `action` and `item_ids` (items to collect again) on every needs_input slot."""
    gaps = [s for s in plan if s.readiness == "needs_input"]
    if not gaps:
        return
    rp = db.scalar(select(ResearchPlan).where(ResearchPlan.project_id == project.id).order_by(ResearchPlan.version.desc()))
    items = list(db.scalars(select(ResearchItem).where(ResearchItem.plan_id == rp.id,
                                                       ResearchItem.selected.is_(True),
                                                       ResearchItem.review_status != "excluded"))) if rp else []
    # 접근 불가 카드는 읽을 내용이 없어 '채택 대기'가 아니다 — access 원인 쪽에서 따로 센다.
    waiting = list(db.scalars(select(Material).join(Source, Source.id == Material.source_id).where(
        Material.project_id == project.id, Material.review_status == "candidate", Material.duplicate_of.is_(None),
        Source.access_status != "unavailable")))
    # Phase 2 커머스 리뷰: Material이 아니라 ReviewSnapshot에 쌓이므로 따로 센다.
    waiting_reviews = list(db.scalars(select(ReviewSnapshot).where(
        ReviewSnapshot.project_id == project.id, ReviewSnapshot.review_status == "candidate",
        ReviewSnapshot.access_status == "ok")))
    # voc 전용: 글은 찾았지만 전부 접근 불가(로그인 벽 등)였던 경우를 "수집 필요"와 구분해 보여준다.
    unavailable = list(db.scalars(select(Material).join(Source, Source.id == Material.source_id).where(
        Material.project_id == project.id, Material.section_id == "voc", Material.duplicate_of.is_(None),
        Source.access_status == "unavailable")))
    # 검색 지수는 자료 카드가 아니라 Fact로 쌓이므로 따로 센다(데이터랩 자동 수집분은 확인 전 candidate).
    waiting_search = {r.data.get("brand_id") for r in db.scalars(select(FactRow).where(
        FactRow.project_id == project.id, FactRow.verification_status == "candidate", FactRow.origin == "auto"))
        if (r.data or {}).get("metric") in ("search_group_sum", "search_index_monthly")}
    waiting_facts: dict[str, set] = {}  # template -> brand ids with candidate numbers for it
    if any(s.template_id in FACT_METRICS for s in gaps):
        for r in db.scalars(select(FactRow).where(FactRow.project_id == project.id, FactRow.origin == "auto",
                                                  FactRow.verification_status == "candidate",
                                                  FactRow.superseded_by.is_(None))):
            metric = (r.data or {}).get("metric")
            for template, metrics in FACT_METRICS.items():
                if metric in metrics:
                    waiting_facts.setdefault(template, set()).add(r.data.get("brand_id"))
    role_of: dict[str, str] = {}
    for b in core.brands:
        role_of.update({c: "competitor" for c in b.competitors})
        role_of.update({x: "benchmark" for x in b.benchmarks})
    role_of.update({b.name: "self" for b in core.brands})

    for slot in gaps:
        section, role = SECTION.get(slot.template_id), _case_role(slot)
        brands = [b for b in core.brands if slot.brand_id in (None, b.id)]

        def mine(brand_id: Optional[str], entity: Optional[str], sec: str) -> bool:
            if sec != section or (slot.brand_id and brand_id not in (None, slot.brand_id)):
                return False
            return role is None or role_of.get(entity or "", "self") == role

        related = [i for i in items if mine(i.brand_id, i.entity, i.section_id)]
        search_fix = _search_setup(slot, brands, related) if section == "search" else None
        if slot.template_id in UPLOAD:
            cause = "upload"
        elif search_fix:
            cause = "setup"
        elif section is None:
            cause = None  # built from the other pages (1-1, recap): nothing of its own to fetch
        elif any(mine(m.brand_id, m.entity, m.section_id) for m in waiting) or \
                any(mine(r.brand_id, r.entity, "commerce_review") for r in waiting_reviews) or \
                (section == "search" and any(b.id in waiting_search for b in brands)) or \
                any(b.id in waiting_facts.get(slot.template_id, ()) for b in brands):
            cause = "adopt"
        elif section == "owned" and not any(p.status == "confirmed" for b in brands for p in b.official_profiles):
            cause = "setup"  # a candidate account still needs a person's check before it can be collected
        elif slot.template_id == "OW-CMP" and not any(p.status == "confirmed" for b in brands
                                                      for ps in b.competitor_profiles.values() for p in ps):
            cause = "setup"
            slot.action = "설정에서 경쟁사 공식 계정 URL을 넣거나, AI가 찾은 후보를 확인하세요 — 자사와 나란히 비교합니다"
        elif section == "voc" and any(mine(m.brand_id, m.entity, m.section_id) for m in unavailable):
            cause = "access"  # found posts, but every one was behind a login wall or otherwise unreachable
        else:
            cause = "collect"  # influencer now searches by brand name on its own — no input required to try
        slot.cause = cause
        if search_fix:
            slot.action = search_fix
        elif cause == "adopt" and section == "search":
            slot.action = "모은 검색 지수가 있습니다 — 자료 확인에서 검색 지수를 확인(채택)하세요"
        elif cause == "adopt" and slot.template_id in FACT_METRICS:
            slot.action = "모은 수치가 있습니다 — 자료 확인에서 수치를 확인(채택)하세요"
        elif slot.action:
            pass  # set above with the cause
        elif cause == "setup":
            slot.action = "설정에서 공식 계정 URL을 넣거나, AI가 찾은 후보를 확인하세요"
        elif cause == "access":
            slot.action = "찾은 글이 모두 로그인 등으로 접근할 수 없었습니다 — 다른 커뮤니티로 다시 찾아보세요"
        elif cause == "collect" and any((i.last_result or {}).get("status") == "failed" for i in related):
            slot.action = "찾은 자료가 없습니다 — 조사 계획에서 다른 표기(영문명 등)를 확인하고 다시 모으세요"
        elif cause:
            slot.action = CAUSES[cause][1]
        # Items to run again: only web-collected ones that did not just succeed with new cards.
        if cause in ("collect", "access"):
            slot.item_ids = [i.id for i in related
                             if i.section_id in ("campaign", "market", "voc", "search", "search_trend", "commerce_review")
                             and i.execution_status not in ("queued", "running")]
