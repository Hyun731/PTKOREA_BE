"""Phase 2 커머스 리뷰 수집 — 확정된 대표 상품(Brand.hero_products_for)의 판매 플랫폼 리뷰를
공개 페이지에서 모은다. 지금은 무신사만 자동 연동(쉬운 곳부터 — 핸드오프 문서 순서)한다.
자동 채택은 없다: 모든 행이 candidate로 시작하고, 사람이 자료 확인에서 채택해야 장표에 쓰인다.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from sqlalchemy.orm import Session

from app.models import Project, ResearchItem, ReviewKeyword, ReviewSnapshot, new_id
from app.services import commerce
from app.services.inputs import core_project
from app.services.ledger import RunLedger
from integrations.base import CallResult, ProviderError
from integrations.commerce import musinsa

KEYWORD_SYSTEM = """당신은 커머스 리뷰를 분류하는 보조입니다. <reviews>는 번호가 매겨진 리뷰 목록입니다
(체험단·협찬 리뷰는 이미 빠져 있습니다).
각 리뷰를 하나씩 보고 긍정/부정/혼재/중립(positive/negative/mixed/neutral) 중 하나로 분류하고,
핵심 키워드(짧은 명사구 1~2개, 예: "쿠션감", "사이즈", "배송")를 답니다. 리뷰에 '그래서 안 살 것
같다'·'비추천'처럼 구매를 막을 만한 불만이 있으면 blocks_purchase를 true로 둡니다(긍정·중립·혼재는
항상 false). 원문에 없는 키워드를 만들지 않습니다."""

KEYWORD_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reviews"],
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "sentiment", "keywords", "blocks_purchase"],
        "properties": {
            "index": {"type": "integer"},
            "sentiment": {"type": "string", "enum": ["positive", "negative", "mixed", "neutral"]},
            "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
            "blocks_purchase": {"type": "boolean"},
        },
    }}},
}

METHOD_NOTE = "AI가 리뷰 본문을 긍정·부정 키워드로 분류(체험단·협찬 리뷰 제외)"

# Test seam, matching the STRUCTURED-list indirection used across app/services/*.py.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def classify_reviews(reviews: list[dict], ledger: RunLedger) -> dict[tuple[str, str], dict]:
    """{(sentiment, keyword): {"indices": [...], "blocks_purchase": bool}} — reviews는 이미 체험단이
    빠진 목록이어야 한다(호출 쪽 책임)."""
    if not reviews:
        return {}
    listing = "\n".join(f"{i}. {r['text'][:300]}" for i, r in enumerate(reviews))
    user = f"<reviews>\n{listing}\n</reviews>"
    try:
        res = ledger.call("anthropic", "commerce_keywords", {"n": len(reviews)}, 0.02,
                          lambda: _structured()(KEYWORD_SYSTEM, user, KEYWORD_SCHEMA, max_tokens=2000),
                          cache_days=None)
    except ProviderError:
        return {}
    out: dict[tuple[str, str], dict] = {}
    for row in res.data.get("reviews") or []:
        idx, sentiment = row.get("index"), row.get("sentiment")
        if sentiment not in ("positive", "negative") or not isinstance(idx, int) or not (0 <= idx < len(reviews)):
            continue
        for kw in (row.get("keywords") or [])[:2]:
            kw = kw.strip()
            if not kw:
                continue
            g = out.setdefault((sentiment, kw), {"indices": [], "blocks_purchase": False})
            g["indices"].append(idx)
            if sentiment == "negative" and row.get("blocks_purchase"):
                g["blocks_purchase"] = True
    return out


def _musinsa_search(ledger: RunLedger, name: str):
    return ledger.call("commerce", "musinsa_search", {"q": name}, 0.0,
                       lambda: CallResult(data=musinsa.find_product(name) or {}), cache_days=7).data or None


def _musinsa_product(ledger: RunLedger, goods_no: str) -> dict:
    return ledger.call("commerce", "musinsa_product", {"goods_no": goods_no}, 0.0,
                       lambda: CallResult(data=musinsa.fetch_product(goods_no)), cache_days=1).data


def _musinsa_reviews(ledger: RunLedger, goods_no: str) -> list[dict]:
    return ledger.call("commerce", "musinsa_reviews", {"goods_no": goods_no}, 0.0,
                       lambda: CallResult(data={"reviews": musinsa.fetch_reviews(goods_no)}), cache_days=1
                       ).data["reviews"]


def run_commerce_item(db: Session, ledger: RunLedger, project: Project, item: ResearchItem) -> dict:
    """item.entity(자사 브랜드 또는 경쟁사)의 확정된 대표 상품마다 무신사에서 평점·리뷰를 모은다."""
    core = core_project(project)
    brand = core.brand(item.brand_id)
    products = brand.hero_products_for(item.entity)
    out: dict = {"created": 0, "snapshots": 0, "keywords": 0, "errors": []}
    if not products:
        out["errors"].append({"code": "NO_PRODUCT", "message":
                              f"{item.entity}의 확정된 대표 상품이 없습니다 — 브랜드 설정에서 확인하세요"})
        return out
    role = "self" if item.entity == brand.name else "competitor"
    today = date.today()
    for product in products:
        found = _musinsa_search(ledger, product.name)
        if not found:
            snap = ReviewSnapshot(id=new_id("REV"), project_id=project.id, brand_id=item.brand_id, entity=item.entity,
                                  role=role, platform="musinsa", product_name=product.name, product_url="",
                                  access_status="unavailable", reason="검색 결과에서 상품을 찾지 못함",
                                  rating_scale=5.0, measured_at=today)
            db.add(snap)
            db.commit()
            out["created"] += 1
            continue
        data = _musinsa_product(ledger, found["goods_no"])
        data["measured_at"] = today  # 파서는 측정일을 모른다 — 검증 전에 수집 시점을 채운다
        bad = commerce.validate_snapshot(data)
        if bad:
            out["errors"].append({"code": "INVALID_SNAPSHOT", "message": f"{product.name}: {bad}"})
            continue
        snap = ReviewSnapshot(id=new_id("REV"), project_id=project.id, brand_id=item.brand_id, entity=item.entity,
                              role=role, platform=data["platform"], product_name=data["product_name"] or product.name,
                              product_url=data["product_url"], access_status=data["access_status"],
                              reason=data.get("reason"), rating=data.get("rating"),
                              rating_scale=data.get("rating_scale") or 5.0, review_count=data.get("review_count"),
                              measured_at=today)
        db.add(snap)
        # 커밋해 쓰기 잠금을 바로 풀어준다 — ledger.call()이 리뷰·키워드 분류마다 별도 커넥션으로
        # commit하는데, 여기서 플러시만 하고 열어 두면 같은 sqlite 파일에 "database is locked"가 난다.
        db.commit()
        out["created"] += 1
        out["snapshots"] += 1
        if data["access_status"] != "ok":
            continue
        reviews = _musinsa_reviews(ledger, found["goods_no"])
        sponsored = [r for r in reviews if r["sponsored"]]
        snap.sponsored_count = len(sponsored)
        organic = [r for r in reviews if not r["sponsored"] and r.get("text")]
        groups = classify_reviews(organic, ledger)
        for (sentiment, keyword), info in groups.items():
            quotes = [{"text": organic[i]["text"][:300], "posted_at": organic[i]["posted_at"]}
                     for i in info["indices"][:3] if organic[i].get("posted_at")]
            kw_data = {"sentiment": sentiment, "keyword": keyword, "sample_size": len(info["indices"]),
                      "method": METHOD_NOTE, "quotes": quotes, "blocks_purchase": info["blocks_purchase"]}
            bad = commerce.validate_keyword(kw_data)
            if bad:
                out.setdefault("dropped", []).append(f"{keyword}: {bad}")
                continue
            db.add(ReviewKeyword(id=new_id("RK"), snapshot_id=snap.id, sentiment=sentiment, keyword=keyword,
                                 sample_size=kw_data["sample_size"], method=METHOD_NOTE, quotes=quotes,
                                 blocks_purchase=info["blocks_purchase"]))
            out["keywords"] += 1
        db.commit()
    return out
