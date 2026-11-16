"""커머스 경쟁 지표(무신사·29CM 공개 목록) — 자사와 경쟁사를 같은 잣대로 잰 숫자.

지향 덱(2번)이 장마다 쓰는 '경쟁사와 같은 지표로 비교한 숫자'를 판매 플랫폼에서 모은다.
- 무신사 판매 랭킹: 브랜드 주력 카테고리의 월간 랭킹(상위 약 100개)을 전체·키 타겟 연령대별로 보고,
  엔티티(자사·경쟁사)의 최고 순위와 100위 안 상품 수를 남긴다.
- 브랜드 최다 후기 상품(SKU): 무신사 '후기순' 첫 상품, 29CM 검색 결과 중 리뷰가 가장 많은 상품 —
  그 상품의 후기 수·찜(좋아요) 수, 그리고 상위 상품 후기 합. 사람이 대표 상품을 고르지 않아도
  데이터가 고른다(대표 상품을 확정하면 그 상품은 commerce_collect가 따로 본다).

값은 모두 확인 전(candidate) Fact다 — 자동 채택은 없다. 막히면(차단·구조 변경) 그 플랫폼만 오류로 남긴다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FactRow, Project, ResearchItem
from app.services.inputs import core_project
from app.services.ledger import RunLedger
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.schemas.facts import Fact
from core.schemas.project import Brand
from integrations.base import CallResult, ProviderError
from integrations.commerce import musinsa, twentyninecm

SOURCES = {"musinsa": "무신사 공개 랭킹·상품 목록", "29cm": "29CM 공개 상품 검색"}
PLATFORM_LABEL = {"musinsa": "무신사", "29cm": "29CM"}
RANK_PERIOD = "MONTHLY"
RANK_DAYS = 30
MAX_CATEGORIES = 2
MAX_TARGET_BANDS = 3
TOP_GOODS = 60  # 후기 합을 내는 상위 상품 수(무신사 후기순 첫 쪽)

# 설정 제품군 이름 → 무신사 카테고리 라벨(띄어쓰기 없이 비교)
CATEGORY_SYNONYMS = {
    "러기지": "캐리어", "여행가방": "캐리어", "수트케이스": "캐리어", "슈트케이스": "캐리어", "트렁크": "캐리어",
    "비즈니스가방": "브리프 케이스", "서류가방": "브리프 케이스", "노트북가방": "브리프 케이스",
    "크로스백": "메신저/크로스 백", "패션가방": "가방", "핸드백": "숄더백",
}

# 테스트가 공급자 호출을 바꿔 끼울 수 있게(STRUCTURED 목록과 같은 방식)
PROVIDERS: dict[str, Callable] = {}


def _p(name: str) -> Callable:
    defaults = {"musinsa_search": musinsa.search_goods, "musinsa_brand_goods": musinsa.brand_goods,
                "musinsa_likes": musinsa.like_counts, "musinsa_rank_categories": musinsa.rank_categories,
                "musinsa_ranking": musinsa.ranking, "29cm_search": twentyninecm.search_brand_goods}
    return PROVIDERS.get(name) or defaults[name]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


# ---------------------------------------------------------------- 매핑

def map_categories(categories: Iterable[str], known: dict[str, str], limit: int = MAX_CATEGORIES) -> list[tuple[str, str]]:
    """설정 제품군 → [(무신사 라벨, 코드)] (겹치면 한 번). 동의어 → 같은 라벨 → 제품군 이름 안에 든 가장 긴 라벨."""
    by_norm = {_norm(k): k for k in known}
    out: list[tuple[str, str]] = []
    for c in categories:
        n = _norm(c)
        label = CATEGORY_SYNONYMS.get(n) or by_norm.get(n)
        if not label:
            inside = [k for nk, k in by_norm.items() if nk and nk in n]
            label = max(inside, key=len) if inside else None
        if label and label in known and all(code != known[label] for _, code in out):
            out.append((label, known[label]))
        if len(out) >= limit:
            break
    return out


def age_bands(brand: Brand) -> list[str]:
    """전체 + 키 타겟 나이와 겹치는 무신사 연령대(최대 MAX_TARGET_BANDS)."""
    out = ["AGE_BAND_ALL"]
    t = brand.target
    if t and (t.age_min is not None or t.age_max is not None):
        lo, hi = t.age_min or 0, t.age_max if t.age_max is not None else 200
        out += [b for b, (a, z) in musinsa.AGE_BAND_RANGE.items() if a <= hi and z >= lo][:MAX_TARGET_BANDS]
    return out


def pick_brand(rows: list[dict], names: list[str], *, prefix: bool) -> Optional[tuple[str, str]]:
    """검색 결과 상품들에서 엔티티의 플랫폼 브랜드(코드, 이름). 이름이 정확히 같은 브랜드를 먼저,
    prefix면 이름으로 시작하는 브랜드(예: '브라이튼' → '브라이튼 캐리어')도 — 가장 많이 나온 것."""
    keys = {_norm(n) for n in names if n}
    exact = Counter((r["brand"], r["brand_name"]) for r in rows
                    if _norm(r["brand_name"]) in keys or _norm(r.get("brand_name_en", "")) in keys
                    or _norm(r["brand"]) in keys)
    if exact:
        return exact.most_common(1)[0][0]
    if prefix:
        starts = Counter((r["brand"], r["brand_name"]) for r in rows
                         if any(_norm(r["brand_name"]).startswith(k) for k in keys))
        if starts and starts.most_common(1)[0][1] >= 3:
            return starts.most_common(1)[0][0]
    return None


# ---------------------------------------------------------------- Fact

def _fact(*, brand_id: str, entity: str, metric: str, value, unit: str, dims: dict, start: date, end: date,
          measured_at: date, platform: str, label: str, url: Optional[str] = None) -> Fact:
    dims = {k: str(v) for k, v in sorted(dims.items())}
    payload = {"brand": brand_id, "entity": entity, "metric": metric, "value": str(value), "unit": unit,
               "dims": json.dumps(dims, ensure_ascii=False, sort_keys=True), "period": f"{start}~{end}",
               "measured_at": measured_at.isoformat(), "source": SOURCES[platform]}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=metric,
                value=Decimal(str(value)), unit=unit, dims=dims, period_start=start, period_end=end,
                measured_at=measured_at, source=SOURCES[platform], url=url, confidence="verified", label=label)


def sku_facts(*, brand_id: str, entity: str, platform: str, goods: list[dict], likes: Optional[int],
              measured_at: date) -> list[Fact]:
    """브랜드 상품들(이미 그 브랜드만) → 최다 후기 상품의 후기 수·찜 수 + 상위 상품 후기 합."""
    goods = [g for g in goods if g.get("review_count") is not None]
    if not goods:
        return []
    top = max(goods, key=lambda g: (g["review_count"], g.get("likes") or 0))
    pl = PLATFORM_LABEL[platform]
    base = {"platform": platform, "product": top["name"][:120], "product_id": top["id"]}
    out = [_fact(brand_id=brand_id, entity=entity, metric="commerce_top_reviews", value=top["review_count"],
                 unit="count", dims=base, start=measured_at, end=measured_at, measured_at=measured_at,
                 platform=platform, label=f"{entity} {pl} 최다 후기 상품 후기 수", url=top["url"]),
           _fact(brand_id=brand_id, entity=entity, metric="commerce_brand_reviews",
                 value=sum(g["review_count"] for g in goods), unit="count",
                 dims={"platform": platform, "n_items": len(goods)}, start=measured_at, end=measured_at,
                 measured_at=measured_at, platform=platform, label=f"{entity} {pl} 상위 {len(goods)}개 상품 후기 합")]
    if likes is not None:
        out.append(_fact(brand_id=brand_id, entity=entity, metric="commerce_top_likes", value=likes, unit="count",
                         dims=base, start=measured_at, end=measured_at, measured_at=measured_at, platform=platform,
                         label=f"{entity} {pl} 최다 후기 상품 찜 수", url=top["url"]))
    return out


def rank_facts(*, brand_id: str, entity: str, platform_brand: str, ranking: list[dict], category: tuple[str, str],
               band: str, measured_at: date) -> list[Fact]:
    """랭킹 한 판 → 엔티티의 최고 순위(있을 때만) + 순위 안 상품 수(0이어도 — '100위 밖'을 말하려고)."""
    label, code = category
    mine = [r for r in ranking if r["brand"] == platform_brand]
    dims = {"platform": "musinsa", "category": code, "category_label": label, "age_band": band, "period": RANK_PERIOD,
            "top_n": len(ranking)}
    start = measured_at - timedelta(days=RANK_DAYS)
    band_label = musinsa.AGE_BANDS.get(band, band)
    out = [_fact(brand_id=brand_id, entity=entity, metric="commerce_ranked_items", value=len(mine), unit="count",
                 dims=dims, start=start, end=measured_at, measured_at=measured_at, platform="musinsa",
                 label=f"{entity} 무신사 {label} 월간 랭킹 {band_label} 상위 {len(ranking)}위 안 상품 수")]
    if mine:
        best = mine[0]
        out.append(_fact(brand_id=brand_id, entity=entity, metric="commerce_best_rank", value=best["rank"],
                         unit="rank", dims={**dims, "product": best["name"][:120]}, start=start, end=measured_at,
                         measured_at=measured_at, platform="musinsa",
                         label=f"{entity} 무신사 {label} 월간 랭킹 {band_label} 최고 순위",
                         url=musinsa.PRODUCT_URL.format(goods_no=best["id"])))
    return out


# ---------------------------------------------------------------- 수집

def _call(ledger: RunLedger, endpoint: str, req: dict, fn: Callable, cache_days: int = 1):
    """공개 목록 호출(무료) — 같은 요청은 하루 캐시(엔티티마다 같은 랭킹을 다시 받지 않게)."""
    return ledger.call("commerce", endpoint, req, 0.0, lambda: CallResult(data={"rows": fn()}),
                       cache_days=cache_days).data["rows"]


def resolve(ledger: RunLedger, platform: str, brand: Brand, entity: str) -> Optional[tuple[str, str]]:
    """엔티티 → 그 플랫폼의 브랜드(코드, 이름). '이름 + 제품군' 검색을 먼저(동명 브랜드 구분), 다음 이름만."""
    names = list(dict.fromkeys([entity, *brand.names_for(entity)]))
    cats = [c for c in brand.categories if c and c != brand.name][:MAX_CATEGORIES]
    search = _p("musinsa_search" if platform == "musinsa" else "29cm_search")
    endpoint = f"{platform}_brand_search"
    for kw, prefix in [*((f"{n} {c}", True) for n in names for c in cats), *((n, False) for n in names)]:
        rows = _call(ledger, endpoint, {"q": kw}, lambda k=kw: search(k), cache_days=7)
        hit = pick_brand(rows, names, prefix=prefix)
        if hit:
            return hit
    return None


def run_commerce_rank(db: Session, ledger: RunLedger, project: Project, item: ResearchItem) -> dict:
    core = core_project(project)
    brand = core.brand(item.brand_id)
    entity = item.entity
    today = date.today()
    out: dict = {"facts": 0, "errors": [], "notes": [], "brands": {}, "ranks": []}
    existing = set(db.scalars(select(FactRow.fact_id).where(FactRow.project_id == project.id)))

    def add(facts: list[Fact], note: str) -> None:
        for f in facts:
            if f.id in existing:
                continue
            db.add(FactRow(project_id=project.id, fact_id=f.id, origin="auto", research_item_id=item.id,
                           data=json.loads(f.model_dump_json()), verification_status="candidate", review_note=note))
            existing.add(f.id)
            out["facts"] += 1

    # 무신사: 브랜드 → 후기순 상품 + 찜 수, 카테고리 랭킹
    try:
        hit = resolve(ledger, "musinsa", brand, entity)
        if not hit:
            out["notes"].append(f"무신사: {entity} 브랜드를 찾지 못함(입점하지 않았을 수 있음)")
        else:
            slug, name = hit
            out["brands"]["musinsa"] = name
            goods = _call(ledger, "musinsa_brand_goods", {"brand": slug, "size": TOP_GOODS},
                          lambda: _p("musinsa_brand_goods")(slug, size=TOP_GOODS))
            likes = None
            if goods:
                top = max(goods, key=lambda g: g["review_count"])
                try:
                    likes = _call(ledger, "musinsa_likes", {"id": top["id"]},
                                  lambda: _p("musinsa_likes")([top["id"]])).get(top["id"])
                except ProviderError as exc:
                    out["errors"].append({"code": exc.code, "message": f"무신사 찜 수: {exc.message}"})
            add(sku_facts(brand_id=item.brand_id, entity=entity, platform="musinsa", goods=goods, likes=likes,
                          measured_at=today), "무신사 브랜드 상품 목록(후기순) 자동 수집")
            known = _call(ledger, "musinsa_rank_categories", {}, _p("musinsa_rank_categories"), cache_days=30)
            cats = map_categories(brand.categories, known)
            if not cats:
                out["notes"].append("무신사 랭킹: 설정 제품군에 맞는 카테고리가 없음")
            for cat in cats:
                for band in age_bands(brand):
                    rows = _call(ledger, "musinsa_ranking", {"cat": cat[1], "age": band, "period": RANK_PERIOD},
                                 lambda c=cat[1], b=band: _p("musinsa_ranking")(c, b, RANK_PERIOD))
                    if not rows:
                        continue
                    facts = rank_facts(brand_id=item.brand_id, entity=entity, platform_brand=slug, ranking=rows,
                                       category=cat, band=band, measured_at=today)
                    add(facts, "무신사 카테고리 월간 랭킹 자동 수집")
                    out["ranks"].append({"category": cat[0], "band": band,
                                         "best": next((int(f.value) for f in facts if f.metric == "commerce_best_rank"), None)})
    except ProviderError as exc:
        out["errors"].append({"code": exc.code, "message": f"무신사: {exc.message}"})
    db.commit()

    # 29CM: 검색 결과 중 그 브랜드 상품 → 최다 후기 상품의 후기·찜 수
    try:
        hit = resolve(ledger, "29cm", brand, entity)
        if not hit:
            out["notes"].append(f"29CM: {entity} 브랜드를 찾지 못함(입점하지 않았을 수 있음)")
        else:
            brand_no, name = hit
            out["brands"]["29cm"] = name
            rows = _call(ledger, "29cm_brand_search", {"q": name}, lambda: _p("29cm_search")(name), cache_days=7)
            goods = [g for g in rows if g["brand"] == brand_no]
            top = max(goods, key=lambda g: g["review_count"]) if goods else None
            add(sku_facts(brand_id=item.brand_id, entity=entity, platform="29cm", goods=goods,
                          likes=top["likes"] if top else None, measured_at=today), "29CM 공개 상품 검색 자동 수집")
    except ProviderError as exc:
        out["errors"].append({"code": exc.code, "message": f"29CM: {exc.message}"})
    db.commit()
    return out
