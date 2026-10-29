"""모두 채택: after reviewing, a person adopts the waiting cards in one step.

A card is adopted together with what makes it usable on a slide — its AI sentences (already checked
against the page), the numbers quoted verbatim from it, and the image it shows. Cards the system has
doubts about are left for a closer look: not relevant, outside the period, period unclear, page not
fetched, or another source of an activity already on a card. Nothing is adopted without a person.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Claim, FactRow, Material, Project, Source, utcnow
from app.services.period import CHECK_PREFIX, OUT_PREFIX

DOUBTS = ("AI 판단: 관련성 낮음", "원문 확보 실패", CHECK_PREFIX, OUT_PREFIX)


def doubt(m: Material, src: Source) -> str | None:
    """Why this card should wait for a person, or None when it can go in."""
    if m.duplicate_of:
        return "같은 사례의 추가 출처"
    if src.access_status not in ("ok", "unknown") and src.source_type != "social":
        return "원문 확보 실패"
    reason = m.review_reason or ""
    return next((d for d in DOUBTS if reason.startswith(d)), None)


def adopt(db: Session, m: Material, who: str) -> None:
    m.review_status, m.reviewed_by, m.reviewed_at = "accepted", who, utcnow()
    for c in db.scalars(select(Claim).where(Claim.material_id == m.id, Claim.review_status == "pending")):
        c.review_status = "accepted"
    for f in db.scalars(select(FactRow).where(FactRow.material_id == m.id, FactRow.verification_status == "candidate",
                                              FactRow.origin.in_(("auto", "manual")), FactRow.superseded_by.is_(None))):
        f.verification_status = "eligible"
    if m.selected_asset_id:
        a = db.get(Asset, m.selected_asset_id)
        if a and a.review_status == "candidate":
            a.review_status = "accepted"
    m.version += 1


def accept_all(db: Session, project: Project, who: str) -> dict:
    """모두 채택: every waiting card the system has no doubt about. Cards with a doubt are left for a look."""
    rows = db.execute(select(Material, Source).join(Source, Source.id == Material.source_id)
                      .where(Material.project_id == project.id, Material.review_status == "candidate")).all()
    accepted, left = [], []
    for m, src in rows:
        if doubt(m, src):
            left.append(m.id)
        else:
            adopt(db, m, who)
            accepted.append(m.id)
    return {"accepted": len(accepted), "left": len(left), "ids": accepted}
