"""Same-activity detection for evidence cards.

Several outlets cover one campaign (often with the brand's press image), so automatic research
would otherwise turn one activity into several C1 cards. A duplicate keeps its own source and
evidence but sits under a primary card and is never used as a slide on its own. Every merge is
reversible, and a card a person split off is never merged back automatically.
"""
from __future__ import annotations

import html
import re
from datetime import date
from typing import Iterable, Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Material, Project, Source
from app.services.inputs import core_project

SPLIT_MARK = "분리됨"  # duplicate_reason of a card a person split off

# Words every campaign headline shares; they say nothing about *which* activity it is.
STOPWORDS = {
    "캠페인", "이벤트", "프로모션", "기획전", "협업", "콜라보", "콜라보레이션", "진행", "전개", "실시", "개최", "운영", "출시",
    "공개", "선봬", "선보여", "선보인다", "선보이다", "론칭", "런칭", "오픈", "팝업", "팝업스토어", "스토어", "매장", "브랜드",
    "신제품", "제품", "컬렉션", "시즌", "한정", "한정판", "고객", "소비자", "마케팅", "여행", "캐리어", "가방", "여행가방",
    "서울", "국내", "글로벌", "공식", "온라인", "기념", "특별", "인기", "대표", "뉴스", "기자", "단독", "종합", "포토",
    "news", "the", "and", "with", "for", "pop", "up", "popup", "event", "campaign", "collection", "new",
    # business-headline verbs and nouns ("러닝 시장 공략 확대") that any two articles of one brand share
    "시장", "공략", "확대", "강화", "확장", "본격", "나서", "나선다", "앞세워", "앞세운", "키운다", "키워", "속도", "효과",
    "성장", "매출", "판매", "인기몰이", "눈길", "주목", "화제", "올해", "새해", "하반기", "상반기", "연속", "모델", "발탁",
}
CATEGORY_SUFFIXES = ("웨어", "복", "룩")
JOSA = ("에서", "으로", "와의", "과의", "에게", "까지", "부터", "와", "과", "의", "을", "를", "이", "가", "에", "로", "은", "는", "도", "만")


def _strip_josa(w: str) -> str:
    for j in JOSA:
        if w.endswith(j) and len(w) - len(j) >= 2:
            return w[: -len(j)]
    return w


def tokens(text: str, names: Iterable[str] = ()) -> set[str]:
    """Distinctive words of a headline: no publisher suffix, particles, stopwords or brand names."""
    head = re.split(r"\s+[-|–—:]{1,2}\s+", html.unescape(text or ""))[0]
    drop = set(STOPWORDS)
    for n in names:
        for w in re.findall(r"[가-힣]+|[a-z][a-z0-9]+", n.lower()):
            w = _strip_josa(w)
            drop.add(w)
            # a category like "러닝웨어" also covers the bare activity word "러닝" in headlines
            for suf in CATEGORY_SUFFIXES:
                if w.endswith(suf) and len(w) - len(suf) >= 2:
                    drop.add(w[: -len(suf)])
    out = set()
    for w in re.findall(r"[가-힣]+|[a-z][a-z0-9]+", re.sub(r"\[[^\]]*\]", " ", head.lower())):
        w = _strip_josa(w)
        if len(w) >= 2 and w not in drop:
            out.add(w)
    return out


def _host(src: Optional[Source]) -> str:
    h = (urlparse(src.original_url).hostname or "") if src and src.original_url else ""
    return h[4:] if h.startswith("www.") else h


def usable(m: Material) -> bool:
    """A card whose original could not be read, or that the AI found off-topic, cannot anchor a group."""
    reason = m.review_reason or ""
    return not (reason.startswith("원문 확보 실패") or reason.startswith("AI 판단: 관련성 낮음"))


def _date(m: Material, src: Optional[Source]) -> Optional[date]:
    return m.activity_date or (src.published_at if src else None)


def same_activity(a: Material, b: Material, *, names: Iterable[str], hashes: dict[str, set[str]],
                  sources: dict[str, Source]) -> Optional[str]:
    """Why a and b look like the same activity, or None."""
    sa, sb = sources.get(a.source_id), sources.get(b.source_id)
    # A site reuses its logo as og:image on every post, so the same image on the same site proves nothing.
    if hashes.get(a.id, set()) & hashes.get(b.id, set()) and _host(sa) != _host(sb):
        return "같은 대표 이미지"
    da, db_ = _date(a, sources.get(a.source_id)), _date(b, sources.get(b.source_id))
    days = abs((da - db_).days) if da and db_ else None
    if days is not None and days > 45:
        return None
    names = list(names)
    ta = tokens(a.title, names) | tokens(a.event_name or "", names)
    tb = tokens(b.title, names) | tokens(b.event_name or "", names)
    shared = sorted(ta & tb, key=len, reverse=True)
    quoted = ", ".join(f"‘{w}’" for w in shared[:3])
    if len(shared) >= 2:
        return f"제목의 {quoted} 일치"
    if shared and len(shared[0]) >= 3 and days is not None and days <= 14:
        return f"제목의 {quoted} 일치 · 날짜 {days}일 차이"
    return None


class Index:
    """Everything detection needs for one project, loaded once."""

    def __init__(self, db: Session, project: Project):
        core = core_project(project)
        self.names = [n for b in core.brands for n in [b.name, *b.aliases, *b.competitors, *b.benchmarks, *b.categories]]
        self.sources = {s.id: s for s in db.scalars(select(Source).where(Source.project_id == project.id))}
        self.hashes: dict[str, set[str]] = {}
        for a in db.scalars(select(Asset).where(Asset.project_id == project.id)):
            if a.material_id:
                self.hashes.setdefault(a.material_id, set()).add(a.sha256)

    def match(self, m: Material, others: Iterable[Material]) -> Optional[tuple[Material, str]]:
        for o in others:
            if o.id == m.id or o.section_id != m.section_id or (o.entity or "") != (m.entity or ""):
                continue
            reason = same_activity(m, o, names=self.names, hashes=self.hashes, sources=self.sources)
            if reason:
                return o, reason
        return None


def primaries(db: Session, project_id: str, section_id: str, entity: Optional[str]) -> list[Material]:
    return list(db.scalars(select(Material).where(
        Material.project_id == project_id, Material.section_id == section_id, Material.entity == entity,
        Material.duplicate_of.is_(None), Material.review_status != "excluded").order_by(Material.created_at)))


def find_duplicate(db: Session, project: Project, m: Material,
                   exclude: frozenset = frozenset()) -> Optional[tuple[Material, str]]:
    """exclude: cards of the same run that are not processed yet (they cannot be a primary yet)."""
    if m.duplicate_reason == SPLIT_MARK:
        return None
    others = [o for o in primaries(db, project.id, m.section_id, m.entity)
              if o.duplicate_reason != SPLIT_MARK and usable(o) and o.id not in exclude]
    return Index(db, project).match(m, others)


def merge(db: Session, m: Material, primary: Material, reason: str) -> None:
    """Put m (and anything already under it) under primary."""
    if primary.duplicate_of:
        primary = db.get(Material, primary.duplicate_of)
    for child in db.scalars(select(Material).where(Material.duplicate_of == m.id)):
        child.duplicate_of = primary.id
        child.version += 1
    m.duplicate_of, m.duplicate_reason = primary.id, reason[:300]
    m.version += 1


def split(m: Material) -> None:
    m.duplicate_of, m.duplicate_reason = None, SPLIT_MARK
    m.version += 1


def scan(db: Session, project: Project) -> list[dict]:
    """Group the project's existing cards. An accepted card stays primary; otherwise the earliest does."""
    idx = Index(db, project)
    mats = list(db.scalars(select(Material).where(
        Material.project_id == project.id, Material.duplicate_of.is_(None), Material.review_status != "excluded",
        Material.section_id.in_(("campaign", "market"))).order_by(Material.created_at)))
    mats.sort(key=lambda m: m.review_status != "accepted")  # stable: accepted first, then by creation
    kept: list[Material] = []
    merged = []
    for m in mats:
        hit = None if m.duplicate_reason == SPLIT_MARK else idx.match(m, [k for k in kept if k.duplicate_reason != SPLIT_MARK and usable(k)])
        if hit:
            merge(db, m, hit[0], hit[1])
            merged.append({"id": m.id, "title": m.title, "primary_id": hit[0].id, "primary_title": hit[0].title, "reason": hit[1]})
        else:
            kept.append(m)
    return merged
