"""자료 확인 화면의 '자사 분석 / 경쟁사 비교' 탭 데이터 (P3-2).

새로 수집하지 않는다. 이미 쌓인 Fact(확인 전 candidate + 확인된 eligible, 각 값에 status 표시)와 장표가
쓰는 파생 수치(P1-2: 댓글 감성·원문 부정률)를 읽어 자사 브랜드 하나와 그 경쟁사를 채널별로 묶는다.
장표(OW-CMP)는 확인된 값만 쓰지만, 이 화면은 기획자가 확인하기 전 값도 보고 판단해야 하므로 함께 싣는다.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from app.errors import not_found
from app.models import Project
from app.services.inputs import load_inputs
from core.composition.compare import CHANNELS, FORMAT_LABEL
from core.composition.formatters import format_value
from core.metrics.derived import POLARITY_LABEL, DerivedInputs, derive, measured_on
from core.rules.config import RulesConfig
from core.schemas.facts import Fact

EMPTY_MESSAGE = "공식 계정을 등록하면 자동으로 채워집니다"
CHANNEL_LABEL = dict(CHANNELS)
SHOWN = ("candidate", "eligible")
# (key, label, metric, formatter) — 채널 KPI 카드 순서. 같은 metric이 형식(동영상/쇼츠)별로 있으면 형식마다 한 줄.
KPIS = [("followers", "팔로워", "owned_followers", "count"),
        ("posts", "월 게시 수", "owned_posts_monthly", "index"),
        ("uploads", "월 업로드 수", "owned_videos_monthly", "index"),
        ("likes", "게시물당 좋아요(중앙값)", "owned_likes_median", "count"),
        ("reactions", "게시물당 반응(중앙값)", "owned_reactions_median", "count"),
        ("comments", "게시물당 댓글(중앙값)", "owned_comments_median", "count"),
        ("shares", "게시물당 공유(중앙값)", "owned_shares_median", "count"),
        ("views", "평균 조회수", "owned_views_avg", "count")]
BLOG_TYPE_LABEL = {"real_use": "실사용", "sponsored": "협찬", "shopping_affiliate": "쇼핑·제휴",
                   "promo_template": "홍보 템플릿", "other": "기타"}
MENTION_CHANNEL_LABEL = {"blog": "블로그", "cafe": "카페", "news": "뉴스", "kin": "지식iN"}
UNIT_FORMAT = {"count": "count", "percent": "share", "index": "index"}


def _value(f: Fact, formatter: Optional[str] = None) -> dict:
    fmt = formatter or UNIT_FORMAT.get(f.unit, "index")
    return {"fact_id": f.id, "value": float(f.value), "display": format_value(fmt, f.value),
            "status": "derived" if f.source == "derived" else f.verification_status,
            "measured_at": f.measured_at.isoformat()}


def _newest(facts: list[Fact]) -> dict:
    """Newest fact per (entity, every dim) — a confirmed value wins over a candidate of the same day."""
    out: dict = {}
    for f in sorted(facts, key=lambda f: (f.measured_at, f.verification_status == "eligible", f.id)):
        out[(f.entity, tuple(sorted(f.dims.items())))] = f
    return out


def summary(db: Session, project: Project, brand_id: Optional[str]) -> dict:
    inputs = load_inputs(db, project)
    core = inputs.project
    brand = next((b for b in core.brands if b.id == brand_id), None) if brand_id else (core.brands or [None])[0]
    if brand is None:
        raise not_found("브랜드")
    entities = [brand.name, *(c for c in brand.competitors if c != brand.name)]
    roles = {e: ("self" if e == brand.name else "competitor") for e in entities}
    facts = [f for f in inputs.facts if f.brand_id == brand.id and f.entity in roles and f.value is not None
             and f.verification_status in SHOWN]
    cfg = RulesConfig.load()
    derived = [f for f in derive(DerivedInputs(project=core, materials=inputs.materials, owned_posts=inputs.owned_posts,
                                               reviews=inputs.reviews,
                                               measured_at=measured_on(core, inputs.materials, inputs.reviews),
                                               min_n=cfg.derived_min_n))
               if f.brand_id == brand.id and f.entity in roles]
    by_metric: dict[str, list[Fact]] = defaultdict(list)
    for f in [*facts, *derived]:
        by_metric[f.metric].append(f)

    channels = [c for c in (_channel(ch, by_metric, entities, brand.name) for ch, _ in CHANNELS) if c]
    out = {
        "brand": {"id": brand.id, "name": brand.name},
        "entities": [{"name": e, "role": roles[e]} for e in entities],
        "channels": channels,
        "pain_points": _pain_points(by_metric["pain_point_count"]),
        "blog_types": _blog_types(by_metric["blog_type_share"]),
        "mentions": _mentions(by_metric["mention_total"], entities),
        "voc_negative": [{"entity": f.entity, "site": f.dims.get("site"), "n": int(f.dims.get("n", 0)), **_value(f, "share")}
                         for f in sorted(by_metric["voc_negative_rate"], key=lambda f: (entities.index(f.entity),
                                                                                         f.dims.get("site") != "전체",
                                                                                         f.dims.get("site", "")))],
    }
    out["has_data"] = any(out[k] for k in ("channels", "pain_points", "blog_types", "mentions", "voc_negative"))
    out["empty"] = None if channels else {"message": EMPTY_MESSAGE, "settings_path": f"/projects/{project.id}/setup"}
    return out


def _channel(channel: str, by_metric: dict, entities: list[str], self_name: str) -> Optional[dict]:
    kpis = []
    for key, label, metric, fmt in KPIS:
        rows = [f for f in by_metric.get(metric, []) if f.dims.get("channel") == channel]
        by_format: dict[Optional[str], dict[str, Fact]] = defaultdict(dict)
        for (entity, _), f in _newest(rows).items():
            by_format[f.dims.get("format")][entity] = f
        for fmt_key in sorted(by_format, key=lambda k: ({None: 0, "video": 1, "shorts": 2}.get(k, 3), k or "")):
            found = by_format[fmt_key]
            values = [{"entity": e, "role": "self" if e == self_name else "competitor", **_value(found[e], fmt)}
                      for e in entities if e in found]
            name = f"{label}({FORMAT_LABEL[fmt_key]})" if fmt_key in FORMAT_LABEL else label
            kpis.append({"key": key + (f"_{fmt_key}" if fmt_key else ""), "label": name, "metric": metric,
                         "format": fmt_key, "values": values, "vs_competitor": _gap(values)})
    months = _monthly(by_metric.get("owned_posts_by_month", []), channel, entities, self_name)
    sentiment = _sentiment(by_metric.get("comment_sentiment_rate", []), channel, entities, self_name)
    if not (kpis or months["series"] or sentiment):
        return None
    return {"channel": channel, "label": CHANNEL_LABEL.get(channel, channel), "kpis": kpis, "monthly_posts": months,
            "sentiment": sentiment}


def _gap(values: list[dict]) -> Optional[dict]:
    """자사 vs 경쟁사 중 가장 높은 곳: 차이와 비율(자사 ÷ 경쟁사 × 100)."""
    own = next((v for v in values if v["role"] == "self"), None)
    comps = [v for v in values if v["role"] == "competitor"]
    if own is None or not comps:
        return None
    top = max(comps, key=lambda v: v["value"])
    ratio = round(own["value"] / top["value"] * 100, 1) if top["value"] else None
    return {"competitor": top["entity"], "diff": round(own["value"] - top["value"], 2), "ratio_pct": ratio}


def _monthly(facts: list[Fact], channel: str, entities: list[str], self_name: str) -> dict:
    rows = _newest([f for f in facts if f.dims.get("channel") == channel])
    months = sorted({f.dims["month"] for f in rows.values() if "month" in f.dims})
    series = []
    for e in entities:
        by_month = {f.dims.get("month"): f for (ent, _), f in rows.items() if ent == e}
        if by_month:
            series.append({"entity": e, "role": "self" if e == self_name else "competitor",
                           "points": [{"month": m, **_value(by_month[m], "count")} if m in by_month else
                                      {"month": m, "value": None} for m in months]})
    return {"months": months, "series": series}


def _sentiment(facts: list[Fact], channel: str, entities: list[str], self_name: str) -> list[dict]:
    rows = [f for f in facts if f.dims.get("channel") == channel]
    out = []
    for e in entities:
        pols = {f.dims["polarity"]: f for f in rows if f.entity == e}
        if not pols:
            continue
        n = int(next(iter(pols.values())).dims.get("n", 0))
        out.append({"entity": e, "role": "self" if e == self_name else "competitor", "n": n, "method": "AI 분류",
                    "rates": [{"polarity": p, "label": POLARITY_LABEL[p], **_value(pols[p], "share")}
                              for p in ("positive", "neutral", "negative") if p in pols]})
    return out


def _pain_points(facts: list[Fact]) -> list[dict]:
    rows = sorted(_newest(facts).values(), key=lambda f: (f.entity, -f.value))
    return [{"entity": f.entity, "pain_point": f.dims.get("pain_point"), "n": int(f.dims["n"]) if "n" in f.dims else None,
             "examples": (f.source_locator or "").split(",")[:3] if f.source_locator else [], **_value(f, "count")}
            for f in rows]


def _blog_types(facts: list[Fact]) -> list[dict]:
    by_kw: dict[str, list[Fact]] = defaultdict(list)
    for f in _newest(facts).values():
        by_kw[f.dims.get("keyword", f.entity)].append(f)
    out = []
    for kw, fs in by_kw.items():
        order = list(BLOG_TYPE_LABEL)
        fs.sort(key=lambda f: order.index(f.dims.get("type")) if f.dims.get("type") in order else len(order))
        out.append({"keyword": kw, "entity": fs[0].entity, "n": int(fs[0].dims["n"]) if "n" in fs[0].dims else None,
                    "shares": [{"type": f.dims.get("type"), "label": BLOG_TYPE_LABEL.get(f.dims.get("type"), f.dims.get("type")),
                                **_value(f, "share")} for f in fs]})
    return out


def _mentions(facts: list[Fact], entities: list[str]) -> list[dict]:
    rows = sorted(_newest(facts).values(), key=lambda f: (entities.index(f.entity), f.dims.get("keyword_group", ""),
                                                          f.dims.get("channel", "")))
    return [{"entity": f.entity, "keyword_group": f.dims.get("keyword_group"), "keyword": f.dims.get("keyword"),
             "channel": f.dims.get("channel"), "channel_label": MENTION_CHANNEL_LABEL.get(f.dims.get("channel"), f.dims.get("channel")),
             **_value(f, "count")} for f in rows]
