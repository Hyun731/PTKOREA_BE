"""업종별 세부 트렌드 키워드 후보 (피드백 #1 하이브리드 설계), candidates only.

core.industry_profiles.INDUSTRY_PROFILES에 확인된(reviewed) 프로필이 없는 업종의 브랜드마다, 그 업계의
구체적인 서브트렌드 키워드(예: 여행업 '트래블룩', '고프코어')를 후보로 낸다. 검토 전 AI 초안 프로필이
있으면 그 keyword_hints를 후보로 쓰고(외부 호출 없음), 없으면 Perplexity 검색 + AI 판단으로 찾는다.
아무것도 자동 채택하지 않는다: 모든 후보는 IndustryKeywordHint(status="candidate")로 남고,
사람이 확인해야(core.schemas.project.Brand.keyword_hints()) 시장 조사(3-1) 검색에 쓰인다.
"""
from __future__ import annotations

from typing import Callable

from app.services.ledger import RunLedger
from core.industry_profiles import INDUSTRY_PROFILES
from integrations.base import ProviderError

SYSTEM = """당신은 한국 마케팅 리서처입니다. <search_results>에서 <industry> 업계의 지금 통하는
세부 트렌드·서브카테고리 키워드를 고릅니다(예: 여행업이면 '트래블룩', '고프코어').
- 검색 결과에 실제로 등장하는 표현만 고릅니다. 만들어내지 않습니다.
- 업계 전체를 가리키는 뻔한 말(예: '트렌드', '성장', '시장')은 빼고 구체적인 용어만 고릅니다.
- 최대 5개. 확신이 없으면 빼고 confident를 false로 둡니다."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["keywords"], "properties": {"keywords": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["text", "confident"],
                               "properties": {"text": {"type": "string"}, "confident": {"type": "boolean"}}}}}}

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


def missing(brand: dict) -> bool:
    """이 브랜드의 업종에 확인된 프로필이 없고, 아직 후보를 낸 적도 없으면 True."""
    industry = brand.get("industry")
    profile = INDUSTRY_PROFILES.get(industry or "")
    if not industry or (profile and profile.reviewed):
        return False
    return not brand.get("industry_keywords")


def discover(industry: str, ledger: RunLedger) -> list[dict]:
    """<industry> 업계의 후보 IndustryKeywordHint dict 목록, 없으면 []."""
    draft = INDUSTRY_PROFILES.get(industry)
    if draft and draft.keyword_hints:  # 검토 전 AI 초안 — 사람이 확인해야 쓰인다
        return [{"text": t, "status": "candidate"} for t in draft.keyword_hints[:5]]
    query = f"{industry} 업계 트렌드 키워드 2026"
    try:
        res = ledger.call("perplexity", "industry_keywords_search", {"industry": industry}, 0.005,
                          lambda: _search()([query], max_results=8), cache_days=30)
    except ProviderError:
        return []
    results = res.data["results"]
    if not results:
        return []
    listing = "\n".join(f"- {r['url']} :: {r['title']} :: {r['snippet'][:160]}" for r in results)
    user = f"<industry>{industry}</industry>\n<search_results>\n{listing}\n</search_results>"
    try:
        ai = ledger.call("anthropic", "industry_keywords_judge", {"industry": industry}, 0.01,
                         lambda: _structured()(SYSTEM, user, SCHEMA, max_tokens=600))
    except ProviderError:
        return []
    out, seen = [], set()
    for row in ai.data.get("keywords") or []:
        text = (row.get("text") or "").strip()
        if not row.get("confident") or not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({"text": text, "status": "candidate"})
    return out[:5]


def fill(cfg: dict, ledger: RunLedger) -> bool:
    """Add candidate keyword hints in place for every brand whose industry still needs them."""
    changed = False
    for b in cfg.get("brands", []):
        if not missing(b):
            continue
        found = discover(b["industry"], ledger)
        if not found:
            continue
        b["industry_keywords"] = [*(b.get("industry_keywords") or []), *found]
        changed = True
    return changed
