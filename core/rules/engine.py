"""Finding rules RULE-R03/R04/R05/R06/R10 (PRD 9 발견 룰).

strength is a sort key, not a probability. Wording limits live in `allowed_expression`
and are enforced by composition/QC (no causal or ad-spend claims).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from core.decimalx import clamp01, q_strength
from core.metrics.engine import MetricsResult
from core.rules.config import RulesConfig
from core.schemas.facts import Finding
from core.schemas.project import Project

ALLOWED = {
    "RULE-R03": "경쟁사 검색 지수 우위 구간 지속",
    "RULE-R04": "브랜드 검색 점유 우위 축소",
    "RULE-R05": "브랜드명 대비 카테고리 탐색 열세",
    "RULE-R06": "키 타겟에서 상대 점유 하락",
    "RULE-R10": "광고 추정 후보에 관측 조회 집중",
}


def run_rules(project: Project, metrics: MetricsResult, config: Optional[RulesConfig] = None) -> list[Finding]:
    config = config or RulesConfig.load()
    findings: list[Finding] = []
    for brand in project.brands:
        findings += _r03(project, brand.id, metrics, config)
        findings += _r04(project, brand.id, metrics, config)
        findings += _r05(project, brand.id, metrics, config)
        findings += _r06(project, brand.id, metrics, config)
        findings += _r10(project, brand.id, metrics, config)
    findings.sort(key=lambda f: (-f.strength, f.rule_id, f.brand_id, f.rival or "", f.cat or ""))
    return findings


def _finding(rule_id: str, brand_id: str, strength: Decimal, summary: dict, fact_ids: list[str], *,
             rival: Optional[str] = None, cat: Optional[str] = None, entities: list[str], windows: list[str]) -> Finding:
    suffix = "-".join(x for x in (rival, cat) if x)
    fid = f"FN-{rule_id.split('-')[1]}-{brand_id}" + (f"-{suffix}" if suffix else "")
    return Finding(id=fid, rule_id=rule_id, brand_id=brand_id, strength=q_strength(clamp01(strength)), summary=summary,
                   fact_ids=fact_ids, rival=rival, cat=cat, entities=entities, windows=windows,
                   allowed_expression=ALLOWED[rule_id])


def _month_index(month: str) -> int:
    y, m = map(int, month.split("-"))
    return y * 12 + m


def _r03(project: Project, brand_id: str, metrics: MetricsResult, config: RulesConfig) -> list[Finding]:
    """Competitor > self for >= N consecutive months. Missing months and ties break runs."""
    series = metrics.monthly_for(brand_id, "all")
    if not series:
        return []
    brand = project.brand(brand_id)
    reg = metrics.registry
    own = series.values.get(brand.name, {})
    out: list[Finding] = []
    for rival in brand.competitors:
        theirs = series.values.get(rival)
        if not theirs:
            continue
        best: list[str] = []
        run: list[str] = []
        for month in series.months:
            a, b = own.get(month), theirs.get(month)
            continuous = run and _month_index(month) == _month_index(run[-1]) + 1
            if a is not None and b is not None and b.value > a.value:  # type: ignore[operator]
                run = run + [month] if continuous else [month]
            else:
                run = []
            # Longest run; equal length -> the more recent one wins.
            if run and len(run) >= len(best):
                best = list(run)
        if len(best) < config.r03_min_months:
            continue
        parents = [own[m].id for m in best] + [theirs[m].id for m in best]
        months_df = reg.derive("run_months", parents, brand_id=brand_id, entity=rival, metric="lead_months",
                               value=len(best), unit="months",
                               params={"start": best[0], "end": best[-1], "scale_id": series.scale_id})
        out.append(_finding(
            "RULE-R03", brand_id, Decimal("0.55") + Decimal("0.05") * len(best),
            {"rival": rival, "start_month": best[0], "end_month": best[-1], "months": len(best)},
            [months_df.id], rival=rival, entities=[brand.name, rival], windows=["monthly"]))
    return out


def _r04(project: Project, brand_id: str, metrics: MetricsResult, config: RulesConfig) -> list[Finding]:
    brand = project.brand(brand_id)
    long = metrics.find_share(brand_id, config.long_window, "all")
    main = metrics.find_share(brand_id, config.main_window, "all")
    if not long or not main or long.entities != main.entities:
        return []
    me = brand.name
    lower = [(long.share(me) - long.share(r), r) for r in brand.competitors if long.share(r) < long.share(me)]
    if not lower:
        return []
    gap_long, rival = min(lower, key=lambda x: (x[0], x[1]))
    if main.share(me) < main.share(rival):
        return []  # reversal is outside this rule
    gap_main = main.share(me) - main.share(rival)
    reduction = gap_long - gap_main
    if reduction < config.r04_min_reduction:
        return []
    reg = metrics.registry
    g12 = reg.derive("diff", [long.shares[me].id, long.shares[rival].id], brand_id=brand_id, entity=rival,
                     metric="share_gap", value=gap_long, unit="pp", params={"window": config.long_window})
    g9 = reg.derive("diff", [main.shares[me].id, main.shares[rival].id], brand_id=brand_id, entity=rival,
                    metric="share_gap", value=gap_main, unit="pp", params={"window": config.main_window})
    red = reg.derive("diff", [g12.id, g9.id], brand_id=brand_id, entity=rival, metric="gap_reduction",
                     value=reduction, unit="pp")
    return [_finding("RULE-R04", brand_id, Decimal("0.5") + reduction / 10,
                     {"rival": rival, "gap_12m": gap_long, "gap_9m": gap_main, "reduction": reduction},
                     [g12.id, g9.id, red.id, long.shares[me].id, long.shares[rival].id,
                      main.shares[me].id, main.shares[rival].id],
                     rival=rival, entities=[me, rival], windows=[config.long_window, config.main_window])]


def _sole_leader(table, entities: list[str]) -> Optional[str]:
    top = max(table.share(e) for e in entities)
    leaders = [e for e in entities if table.share(e) == top]
    return leaders[0] if len(leaders) == 1 else None


def _r05(project: Project, brand_id: str, metrics: MetricsResult, config: RulesConfig) -> list[Finding]:
    brand = project.brand(brand_id)
    me = brand.name
    name_table = metrics.find_share(brand_id, config.main_window, "all")
    if not name_table or _sole_leader(name_table, name_table.entities) != me:
        return []
    out: list[Finding] = []
    for cat in metrics.cats(brand_id, config.main_window, "all"):
        t = metrics.find_share(brand_id, config.main_window, "all", cat)
        if not t:
            continue
        leader = _sole_leader(t, t.entities)
        if leader is None or leader == me:
            continue
        self_share, rival_share = t.share(me), t.share(leader)
        if self_share > rival_share * config.r05_max_self_ratio:
            continue
        out.append(_finding(
            "RULE-R05", brand_id, Decimal("0.6") + Decimal("0.4") * (1 - self_share / rival_share),
            {"cat": cat, "rival": leader, "self_share": self_share, "rival_share": rival_share},
            [t.shares[me].id, t.shares[leader].id, t.ranks[leader].id, name_table.ranks[me].id],
            rival=leader, cat=cat, entities=[me, leader], windows=[config.main_window]))
    return out


def _r06(project: Project, brand_id: str, metrics: MetricsResult, config: RulesConfig) -> list[Finding]:
    me = project.brand(brand_id).name
    all_t = metrics.find_share(brand_id, config.main_window, "all")
    tgt = metrics.find_share(brand_id, config.main_window, "T")
    if not all_t or not tgt:
        return []
    if all_t.entities != tgt.entities or (all_t.period_start, all_t.period_end) != (tgt.period_start, tgt.period_end):
        return []
    a, t = all_t.share(me), tgt.share(me)
    if not t < a:
        return []
    diff = metrics.registry.derive("diff", [tgt.shares[me].id, all_t.shares[me].id], brand_id=brand_id, entity=me,
                                   metric="target_share_diff", value=t - a, unit="pp",
                                   params={"window": config.main_window, "from": "all", "to": "T"})
    return [_finding("RULE-R06", brand_id, Decimal("0.5") + (a - t) / 20,
                     {"all": a, "target": t, "diff": t - a},
                     [all_t.shares[me].id, tgt.shares[me].id, diff.id],
                     entities=[me], windows=[f"{config.main_window}:all", f"{config.main_window}:T"])]


def _r10(project: Project, brand_id: str, metrics: MetricsResult, config: RulesConfig) -> list[Finding]:
    ad = metrics.ad.get(brand_id)
    if not ad or ad.ad_view_share is None or ad.coverage is None or ad.view_eligible_posts is None:
        return []
    share, cov = ad.ad_view_share.value, ad.coverage.value
    n_posts = ad.view_eligible_posts.value
    if n_posts < config.r10_min_view_posts or cov < config.r10_min_coverage or share < config.r10_min_ad_share:  # type: ignore[operator]
        return []
    return [_finding("RULE-R10", brand_id, Decimal("0.5") + share / 200,  # type: ignore[operator]
                     {"ad_share": share, "ad_posts": ad.ad_posts.value if ad.ad_posts else 0,
                      "coverage": cov, "view_eligible_posts": n_posts},
                     [ad.ad_view_share.id, ad.coverage.id],
                     entities=[], windows=["posts"])]
