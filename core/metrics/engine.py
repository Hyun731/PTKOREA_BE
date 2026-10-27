"""Quantitative formulas (PRD 9 계산 규칙). Pure functions over eligible Facts and Posts.

Shares need the full configured set (self + competitors); a partial set never gets a
re-based denominator. Ranks use unrounded values with 1,1,3 ties.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from core.metrics.registry import FactRegistry
from core.rules.config import RulesConfig
from core.schemas.facts import DerivedFact, Fact, Post
from core.schemas.project import Brand, Project

HUNDRED = Decimal(100)


@dataclass
class MetricIssue:
    code: str
    message: str
    brand_id: Optional[str] = None
    detail: dict = field(default_factory=dict)


@dataclass
class ShareTable:
    brand_id: str
    formula: str  # share | share_combo
    window: str
    seg: str
    scale_id: str
    cat: Optional[str]
    period_start: date
    period_end: date
    entities: list[str]  # configured order
    raw: dict[str, Fact]
    shares: dict[str, DerivedFact]
    ranks: dict[str, DerivedFact]
    total: Decimal

    def share(self, entity: str) -> Decimal:
        return self.shares[entity].value  # type: ignore[return-value]

    def ordered(self) -> list[str]:
        """Entities by unrounded share desc, then configured order (stable)."""
        return sorted(self.entities, key=lambda e: (-self.share(e), self.entities.index(e)))


@dataclass
class MonthlySeries:
    brand_id: str
    seg: str
    scale_id: str
    months: list[str]
    values: dict[str, dict[str, Fact]]  # entity -> month -> fact


@dataclass
class PostMetrics:
    post: Post
    er: Optional[DerivedFact]
    like_view: Optional[DerivedFact]
    ad_heuristic: DerivedFact  # value True / False / "unknown"


@dataclass
class AdSummary:
    brand_id: str
    ad_view_share: Optional[DerivedFact]
    coverage: Optional[DerivedFact]
    ad_posts: Optional[DerivedFact]
    view_eligible_posts: Optional[DerivedFact]


@dataclass
class MetricsResult:
    registry: FactRegistry
    share_tables: list[ShareTable]
    monthly: list[MonthlySeries]
    posts: dict[str, list[PostMetrics]]  # brand_id -> metrics in post order
    ad: dict[str, AdSummary]
    issues: list[MetricIssue]

    def find_share(self, brand_id: str, window: str, seg: str, cat: Optional[str] = None) -> Optional[ShareTable]:
        matches = [t for t in self.share_tables
                   if t.brand_id == brand_id and t.window == window and t.seg == seg and t.cat == cat]
        return matches[0] if len(matches) == 1 else None

    def cats(self, brand_id: str, window: str, seg: str = "all") -> list[str]:
        return sorted({t.cat for t in self.share_tables
                       if t.brand_id == brand_id and t.window == window and t.seg == seg and t.cat})

    def monthly_for(self, brand_id: str, seg: str = "all") -> Optional[MonthlySeries]:
        matches = [m for m in self.monthly if m.brand_id == brand_id and m.seg == seg]
        return matches[0] if len(matches) == 1 else None


def competition_ranks(values: dict[str, Decimal]) -> dict[str, int]:
    """Standard competition ranking on unrounded values: 1,1,3."""
    ranks: dict[str, int] = {}
    for name, v in values.items():
        ranks[name] = 1 + sum(1 for other in values.values() if other > v)
    return ranks


def compute(project: Project, facts: list[Fact], posts: list[Post], config: Optional[RulesConfig] = None) -> MetricsResult:
    config = config or RulesConfig.load()
    usable = [f for f in facts if f.usable and f.conflict_key is None]
    registry = FactRegistry(facts)
    issues: list[MetricIssue] = []
    for f in facts:
        if f.conflict_key and f.verification_status == "eligible":
            issues.append(MetricIssue("SOURCE_CONFLICT", f"제공자 간 값 충돌로 보류: {f.entity} {f.metric}", f.brand_id,
                                      {"natural_key": f.conflict_key}))
    tables = _share_tables(project, usable, registry, issues)
    monthly = _monthly(project, usable, issues)
    post_metrics: dict[str, list[PostMetrics]] = {}
    ad: dict[str, AdSummary] = {}
    for brand in project.brands:
        bposts = [p for p in posts if p.brand_id == brand.id and p.verification_status == "eligible"]
        pm = [_post_metrics(p, registry, config) for p in bposts]
        post_metrics[brand.id] = pm
        ad[brand.id] = _ad_summary(project, brand, pm, registry, issues)
    return MetricsResult(registry, tables, monthly, post_metrics, ad, issues)


def _share_tables(project: Project, facts: list[Fact], registry: FactRegistry, issues: list[MetricIssue]) -> list[ShareTable]:
    groups: dict[tuple, list[Fact]] = {}
    for f in facts:
        if f.metric != "search_group_sum":
            continue
        key = (f.brand_id, f.dims["window"], f.dims["seg"], f.period_start, f.period_end, f.dims["scale_id"], f.dims.get("cat"))
        groups.setdefault(key, []).append(f)

    tables: list[ShareTable] = []
    for key, members in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        brand_id, window, seg, start, end, scale_id, cat = key
        brand = project.brand(brand_id)
        entities = brand.entity_set
        by_entity = {f.entity: f for f in members}
        missing = [e for e in entities if e not in by_entity]
        label = f"{brand.name} {window}·{seg}" + (f"·{cat}" if cat else "")
        if missing:
            issues.append(MetricIssue("INCOMPLETE_SET", f"{label}: {', '.join(missing)} 값이 없어 점유를 만들지 않습니다",
                                      brand_id, {"missing": missing, "scale_id": scale_id}))
            continue
        total = sum((by_entity[e].value for e in entities), Decimal(0))  # type: ignore[misc]
        if total == 0:
            issues.append(MetricIssue("ZERO_DENOMINATOR", f"{label}: 분모 0", brand_id))
            continue
        formula = "share_combo" if cat else "share"
        parents = [by_entity[e].id for e in entities]
        params = {"window": window, "seg": seg, "scale_id": scale_id, "cat": cat, "period": f"{start}~{end}"}
        shares: dict[str, DerivedFact] = {}
        raw_values: dict[str, Decimal] = {}
        for e in entities:
            value = by_entity[e].value / total * HUNDRED  # type: ignore[operator]
            raw_values[e] = value
            shares[e] = registry.derive(formula, parents, brand_id=brand_id, entity=e, metric="search_share",
                                        value=value, unit="percent", params=params,
                                        definition="검색어 그룹 상대 지수 합 기준 세트 내 비중")
        ranks: dict[str, DerivedFact] = {}
        for e, r in competition_ranks(raw_values).items():
            ranks[e] = registry.derive("rank", [shares[x].id for x in entities], brand_id=brand_id, entity=e,
                                       metric="search_share_rank", value=r, unit="rank", params=params)
        tables.append(ShareTable(brand_id, formula, window, seg, scale_id, cat, start, end, entities,
                                 by_entity, shares, ranks, total))

    # A (brand, window, seg, cat) slot with more than one scale/period is ambiguous.
    slots: dict[tuple, int] = {}
    for t in tables:
        slots[(t.brand_id, t.window, t.seg, t.cat)] = slots.get((t.brand_id, t.window, t.seg, t.cat), 0) + 1
    for slot, n in slots.items():
        if n > 1:
            issues.append(MetricIssue("AMBIGUOUS_SCALE", f"{slot}: 서로 다른 scale/기간 세트가 {n}개라 비교에 사용하지 않습니다",
                                      slot[0]))
    return tables


def _monthly(project: Project, facts: list[Fact], issues: list[MetricIssue]) -> list[MonthlySeries]:
    groups: dict[tuple, list[Fact]] = {}
    for f in facts:
        if f.metric != "search_index_monthly":
            continue
        groups.setdefault((f.brand_id, f.dims["seg"], f.dims["scale_id"]), []).append(f)
    out: list[MonthlySeries] = []
    for (brand_id, seg, scale_id), members in sorted(groups.items()):
        values: dict[str, dict[str, Fact]] = {}
        for f in members:
            values.setdefault(f.entity, {})[f.dims["month"]] = f
        months = sorted({m for v in values.values() for m in v})
        brand = project.brand(brand_id)
        if brand.name not in values:
            issues.append(MetricIssue("INCOMPLETE_SET", f"{brand.name} 월별 지수에 자사 값이 없습니다", brand_id))
            continue
        out.append(MonthlySeries(brand_id, seg, scale_id, _fill_months(months), values))
    return out


def _fill_months(months: list[str]) -> list[str]:
    """Continuous month axis; gaps stay visible as gaps (never interpolated)."""
    if not months:
        return []
    y, m = map(int, months[0].split("-"))
    ey, em = map(int, months[-1].split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _post_metrics(post: Post, registry: FactRegistry, config: RulesConfig) -> PostMetrics:
    params = {"post_id": post.post_id}
    er = None
    if (post.followers and post.followers > 0 and post.comments is not None
            and (post.likes is not None or post.likes_hidden)):
        likes = 0 if post.likes_hidden else post.likes
        value = Decimal(likes + post.comments) / Decimal(post.followers) * HUNDRED  # type: ignore[operator]
        parents = [post.fact_ids[k] for k in ("followers", "likes", "comments") if k in post.fact_ids]
        er = registry.derive("er", parents, brand_id=post.brand_id, entity=post.creator, metric="engagement_rate",
                             value=value, unit="percent", params={**params, "rate_basis": post.rate_basis},
                             partial=post.likes_hidden,
                             definition="(좋아요+댓글)÷팔로워(YouTube는 구독자)×100" + (" · 좋아요 비공개: 댓글만 반영한 부분 반응률" if post.likes_hidden else ""))
    like_view = None
    if post.views and post.views > 0 and post.likes is not None and not post.likes_hidden:
        value = Decimal(post.likes) / Decimal(post.views) * HUNDRED
        like_view = registry.derive("like_view", [post.fact_ids["likes"], post.fact_ids["views"]], brand_id=post.brand_id,
                                    entity=post.creator, metric="like_view_rate", value=value, unit="percent", params=params)
    if like_view is None:
        heuristic: object = "unknown"
        parents = [fid for fid in post.fact_ids.values()]
    else:
        heuristic = like_view.value < config.ad_like_view_threshold  # type: ignore[operator]
        parents = [like_view.id]
    ad = registry.derive("ad_heuristic", parents, brand_id=post.brand_id, entity=post.creator, metric="ad_candidate",
                         value=heuristic, unit="flag",
                         params={**params, "threshold": config.ad_like_view_threshold},
                         definition="좋아요÷조회 < 기준값인 게시물을 광고 추정 후보로 분류(광고 구매 증거 아님)")
    return PostMetrics(post, er, like_view, ad)


def _in_period(project: Project, post: Post) -> bool:
    window = project.window_for("influencer")
    if window:
        return window.start <= post.posted_at <= window.end
    return project.period.contains(post.posted_at)


def _ad_summary(project: Project, brand: Brand, pms: list[PostMetrics], registry: FactRegistry,
                issues: list[MetricIssue]) -> AdSummary:
    sample = [pm for pm in pms if pm.post.owner_type == "creator" and _in_period(project, pm.post)
              and pm.post.views is not None]
    if not sample:
        return AdSummary(brand.id, None, None, None, None)
    denom = sum(pm.post.views for pm in sample)  # type: ignore[misc]
    view_parents = [pm.post.fact_ids["views"] for pm in sample]
    eligible_n = registry.derive("count", view_parents, brand_id=brand.id, metric="view_eligible_posts",
                                 value=len(sample), unit="count", params={"scope": "creator_posts_with_views"})
    if denom == 0:
        issues.append(MetricIssue("ZERO_DENOMINATOR", f"{brand.name}: creator 게시물 조회 합이 0", brand.id))
        return AdSummary(brand.id, None, None, None, eligible_n)
    candidates = [pm for pm in sample if pm.ad_heuristic.value is True]
    classified = [pm for pm in sample if pm.like_view is not None]
    parents = view_parents + [pm.ad_heuristic.id for pm in sample]
    share_value = Decimal(sum(pm.post.views for pm in candidates)) / Decimal(denom) * HUNDRED  # type: ignore[misc]
    cov_value = Decimal(sum(pm.post.views for pm in classified)) / Decimal(denom) * HUNDRED  # type: ignore[misc]
    ad_share = registry.derive("ad_view_share", parents, brand_id=brand.id, metric="ad_view_share", value=share_value,
                               unit="percent", definition="광고 추정 후보 조회 합÷조회가 있는 기간 내 creator 게시물 조회 합")
    coverage = registry.derive("classification_coverage", parents, brand_id=brand.id, metric="classification_coverage",
                               value=cov_value, unit="percent",
                               definition="좋아요÷조회를 계산할 수 있는 게시물 조회 합÷같은 분모")
    ad_posts = registry.derive("count", [pm.ad_heuristic.id for pm in sample], brand_id=brand.id, metric="ad_candidate_posts",
                               value=len(candidates), unit="count")
    return AdSummary(brand.id, ad_share, coverage, ad_posts, eligible_n)
