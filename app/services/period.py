"""Research period guard: collected material must describe an activity inside the item's period.

Three places use it:
  search   — the search request carries a publish-date window (a little wider than the period:
             an article shortly before the start can announce an in-period activity);
  intake   — results whose publish date is clearly outside that window are not even fetched;
  review   — after AI extraction the activity date decides: outside → excluded with a reason,
             unknown and near the edge → kept but flagged for a person to check.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Material, Project, ResearchItem, Source

LEAD_DAYS = 30  # announcements published up to a month before the period may cover in-period activity
TAIL_DAYS = 14  # reports shortly after the end may still describe an in-period activity
OUT_PREFIX = "조사 기간 밖"
CHECK_PREFIX = "기간 확인 필요"
AUTO_ADOPTER = "AI 기본 채택"  # reviewed_by of cards that went in by default, not by a person

Status = Literal["in", "check", "out"]


def search_window(start: date, end: date) -> tuple[date, date]:
    return start - timedelta(days=LEAD_DAYS), end + timedelta(days=TAIL_DAYS)


def search_windows(start: date, end: date, parts: int = 3, min_days: int = 45) -> list[tuple[date, date]]:
    """Split the search window into up to `parts` consecutive ranges of at least `min_days` each."""
    lo, hi = search_window(start, end)
    total = (hi - lo).days + 1
    k = max(1, min(parts, total // min_days))
    step = total / k
    out = []
    for i in range(k):
        a = lo + timedelta(days=round(i * step))
        b = hi if i == k - 1 else lo + timedelta(days=round((i + 1) * step) - 1)
        out.append((a, b))
    return out


def mmddyyyy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def published_in_search_window(published: Optional[date], start: date, end: date) -> bool:
    if published is None:
        return True  # undated results are judged after extraction
    lo, hi = search_window(start, end)
    return lo <= published <= hi


def classify(start: date, end: date, activity: Optional[date], activity_end: Optional[date],
             published: Optional[date]) -> tuple[Status, str]:
    """(status, reason). The activity date wins over the publish date when both are known."""
    period = f"기간 {start:%Y.%m.%d}~{end:%Y.%m.%d}"
    if activity:
        last = activity_end or activity
        if last < start or activity > end:
            span = f"{activity:%Y.%m.%d}" + (f"~{activity_end:%Y.%m.%d}" if activity_end and activity_end != activity else "")
            return "out", f"{OUT_PREFIX}: 활동 {span} ({period})"
        return "in", ""
    if published is None:
        return "check", f"{CHECK_PREFIX}: 활동일·발행일 미확인 ({period})"
    lo, hi = search_window(start, end)
    if published < lo or published > hi:
        return "out", f"{OUT_PREFIX}: 발행 {published:%Y.%m.%d}, 활동일 미확인 ({period})"
    if published < start or published > end:
        return "check", f"{CHECK_PREFIX}: 발행 {published:%Y.%m.%d}, 활동일 미확인 ({period})"
    return "in", ""


def apply(m: Material, item: ResearchItem, src: Source) -> Status:
    """Mark a candidate card by the period rule. Never touches a card a person already reviewed."""
    by_default = m.review_status == "accepted" and m.reviewed_by == AUTO_ADOPTER
    if (m.review_status not in ("candidate", "excluded") and not by_default) or m.input_path != "auto":
        return "in"
    status, reason = classify(item.period_start, item.period_end, m.activity_date, m.activity_date_end, src.published_at)
    if status == "out":
        m.review_status, m.review_reason = "excluded", reason
    elif status == "check":
        if by_default:  # an unclear date is a doubt: back to waiting for a person
            m.review_status = "candidate"
        if not (m.review_reason or "").startswith(CHECK_PREFIX):
            m.review_reason = reason + (f" · {m.review_reason}" if m.review_reason else "")
    elif m.review_status == "excluded" and (m.review_reason or "").startswith(OUT_PREFIX):
        m.review_status, m.review_reason = "candidate", None  # dates were corrected since
    return status


def recheck(db: Session, project: Project) -> dict:
    """Apply the rule to the project's existing auto-collected candidates."""
    rows = db.execute(select(Material, ResearchItem, Source)
                      .join(ResearchItem, ResearchItem.id == Material.research_item_id)
                      .join(Source, Source.id == Material.source_id)
                      .where(Material.project_id == project.id, Material.input_path == "auto",
                             or_(Material.review_status.in_(("candidate", "excluded")),
                                 Material.reviewed_by == AUTO_ADOPTER))).all()
    out = {"checked": 0, "excluded": [], "flagged": 0}
    for m, item, src in rows:
        before = m.review_status
        st = apply(m, item, src)
        out["checked"] += 1
        if st == "out" and before != "excluded":
            out["excluded"].append({"id": m.id, "title": m.title, "reason": m.review_reason})
        elif st == "check":
            out["flagged"] += 1
    return out
