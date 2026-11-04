"""Why a planned slide has no page yet, and what fixes it (팩트북 출력 · 초안 흐름).

A missing slide reads as "자료 없음" either way, but the fix differs: cards waiting to be adopted,
a search that found nothing, a setting the collector needs, or a CSV only a person can upload.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, Project, ResearchItem, ResearchPlan, Source
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
           "5-1": "voc", "5-2": "voc"}
UPLOAD = {"2-8a", "2-8b", "2-8c", "2-8d"}  # search volumes come from a CSV (no Naver API)


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
    # voc 전용: 글은 찾았지만 전부 접근 불가(로그인 벽 등)였던 경우를 "수집 필요"와 구분해 보여준다.
    unavailable = list(db.scalars(select(Material).join(Source, Source.id == Material.source_id).where(
        Material.project_id == project.id, Material.section_id == "voc", Material.duplicate_of.is_(None),
        Source.access_status == "unavailable")))
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
        if slot.template_id in UPLOAD:
            cause = "upload"
        elif section is None:
            cause = None  # built from the other pages (1-1, recap): nothing of its own to fetch
        elif any(mine(m.brand_id, m.entity, m.section_id) for m in waiting):
            cause = "adopt"
        elif section == "owned" and not any(p.status == "confirmed" for b in brands for p in b.official_profiles):
            cause = "setup"  # a candidate account still needs a person's check before it can be collected
        elif section == "voc" and any(mine(m.brand_id, m.entity, m.section_id) for m in unavailable):
            cause = "access"  # found posts, but every one was behind a login wall or otherwise unreachable
        else:
            cause = "collect"  # influencer now searches by brand name on its own — no input required to try
        slot.cause = cause
        if cause == "setup":
            slot.action = "설정에서 공식 계정 URL을 넣거나, AI가 찾은 후보를 확인하세요"
        elif cause == "access":
            slot.action = "찾은 글이 모두 로그인 등으로 접근할 수 없었습니다 — 다른 커뮤니티로 다시 찾아보세요"
        elif cause == "collect" and any((i.last_result or {}).get("status") == "failed" for i in related):
            slot.action = "찾은 자료가 없습니다 — 조사 계획에서 다른 표기(영문명 등)를 확인하고 다시 모으세요"
        elif cause:
            slot.action = CAUSES[cause][1]
        # Items to run again: only web-collected ones that did not just succeed with new cards.
        if cause in ("collect", "access"):
            slot.item_ids = [i.id for i in related if i.section_id in ("campaign", "market", "voc")
                             and i.execution_status not in ("queued", "running")]
