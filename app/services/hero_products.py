"""Hero/기획 products per brand entity (Phase 2 커머스 리뷰), candidates only.

For each entity (a self brand or one of its competitors) with no hero products yet, a Perplexity
search plus an AI read of the results propose candidate product names — the ones that drive
revenue (Hero) or draw attention (한정판·콜라보 등 기획 상품). Nothing is ever auto-confirmed:
every candidate sits as HeroProduct(status="candidate") until a person checks it, matching the
project rule that materials are never auto-adopted. Review collection (commerce.py) only ever
reads confirmed products (core.schemas.project.Brand.hero_products_for).
"""
from __future__ import annotations

from typing import Callable

from app.services.ledger import RunLedger
from integrations.base import ProviderError

SYSTEM = """당신은 한국 브랜드의 대표 상품을 찾는 리서처입니다. <search_results>에서 <brand>의 매출을 끄는
대표 상품(Hero)과 기획 상품(한정판·콜라보 등 화제성 있는 상품)을 고릅니다.
- 검색 결과에 실제로 이름이 등장하는 상품만 고릅니다. 만들어내지 않습니다.
- 최대 3개. 상품명은 정확한 제품명으로(시리즈명만으로 뭉뚱그리지 않음).
- 확신이 없으면 빼고 confident를 false로 둡니다."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["products"], "properties": {"products": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["name", "confident"],
                               "properties": {"name": {"type": "string"}, "confident": {"type": "boolean"}}}}}}

# Indirection so tests can stub the model call and the search call.
STRUCTURED: list[Callable] = []
SEARCH: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def _search():
    if not SEARCH:
        from integrations.perplexity.client import search
        SEARCH.append(search)
    return SEARCH[0]


def missing(brand: dict) -> list[str]:
    """Entities (self + competitors) that have no hero products yet, confirmed or not."""
    out = []
    if not brand.get("hero_products"):
        out.append(brand["name"])
    chp = brand.get("competitor_hero_products") or {}
    out += [c for c in brand.get("competitors", []) if not chp.get(c)]
    return out


def discover(name: str, category_hint: str, ledger: RunLedger) -> list[dict]:
    """Candidate HeroProduct dicts for one entity, or [] if nothing is found or confirmed."""
    query = f"{name} 대표 상품 베스트셀러 인기 상품 한정판 콜라보"
    try:
        res = ledger.call("perplexity", "hero_products_search", {"name": name}, 0.005,
                          lambda: _search()([query], max_results=8), cache_days=7)
    except ProviderError:
        return []
    results = res.data["results"]
    if not results:
        return []
    listing = "\n".join(f"- {r['url']} :: {r['title']} :: {r['snippet'][:160]}" for r in results)
    user = f"<brand>{name}</brand>\n<category>{category_hint}</category>\n<search_results>\n{listing}\n</search_results>"
    try:
        ai = ledger.call("anthropic", "hero_products_judge", {"name": name}, 0.01,
                         lambda: _structured()(SYSTEM, user, SCHEMA, max_tokens=600))
    except ProviderError:
        return []
    out, seen = [], set()
    for row in ai.data.get("products") or []:
        name_ = (row.get("name") or "").strip()
        if not row.get("confident") or not name_ or name_.lower() in seen:
            continue
        seen.add(name_.lower())
        out.append({"name": name_, "status": "candidate"})
    return out[:3]


def fill(cfg: dict, ledger: RunLedger) -> bool:
    """Add candidate products in place for every entity still missing them. True when it changed."""
    changed = False
    for b in cfg.get("brands", []):
        hint = ", ".join(b.get("categories", [])) or b["name"]
        for name in missing(b):
            found = discover(name, hint, ledger)
            if not found:
                continue
            if name == b["name"]:
                b["hero_products"] = [*(b.get("hero_products") or []), *found]
            else:
                chp = dict(b.get("competitor_hero_products") or {})
                chp[name] = [*chp.get(name, []), *found]
                b["competitor_hero_products"] = chp
            changed = True
    return changed
