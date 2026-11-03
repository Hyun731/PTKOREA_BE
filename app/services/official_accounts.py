"""Official social accounts per brand entity (Phase 1-1 브랜드 카드), candidates only.

For each entity (a self brand or one of its competitors) that has no official account entries at
all yet, a Perplexity search plus an AI read of the results propose candidate URLs per channel.
Nothing is ever auto-confirmed — every candidate sits as OfficialProfile(status="candidate") until
a person checks it, matching the project rule that materials are never auto-adopted.
"""
from __future__ import annotations

from typing import Callable

from app.services.ledger import RunLedger
from integrations.base import ProviderError

CHANNELS: tuple[str, ...] = ("instagram", "youtube", "facebook", "x", "threads", "blog")
CHANNEL_LABEL: dict[str, str] = {"instagram": "Instagram", "youtube": "YouTube", "facebook": "Facebook",
                                 "x": "X", "threads": "Threads", "blog": "블로그"}
# ScrapeCreators only has Instagram/YouTube collectors (run_owned_item); the rest can be found as a
# candidate account but their posts are never collected automatically.
AUTO_COLLECTABLE: tuple[str, ...] = ("instagram", "youtube")
# A candidate's url must actually belong to that platform, or a bad AI guess becomes a bad suggestion.
CHANNEL_DOMAIN: dict[str, tuple[str, ...]] = {
    "instagram": ("instagram.com",), "youtube": ("youtube.com", "youtu.be"), "facebook": ("facebook.com", "fb.com"),
    "x": ("x.com", "twitter.com"), "threads": ("threads.net",), "blog": ("blog.naver.com", "tistory.com"),
}

SYSTEM = """당신은 한국 브랜드의 공식 SNS 계정을 찾는 리서처입니다. <search_results>에서 <brand>의 공식 계정만 고릅니다.
- 그 브랜드가 직접 운영하는 공식 계정만 고릅니다. 팬 계정, 판매처, 기사, 다른 브랜드는 제외합니다.
- 검색 결과에 없는 URL은 만들지 않습니다. 결과 안에서만 고릅니다.
- 채널마다 가장 확실한 것 하나만 고르고, 확신이 없으면 그 채널은 빼고 confident를 false로 둡니다."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["profiles"], "properties": {"profiles": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["channel", "url", "confident"],
                               "properties": {"channel": {"type": "string", "enum": list(CHANNELS)},
                                              "url": {"type": "string"}, "confident": {"type": "boolean"}}}}}}

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
    """Entities (self + competitors) that have no official account entries yet, confirmed or not."""
    out = []
    if not brand.get("official_profiles"):
        out.append(brand["name"])
    cp = brand.get("competitor_profiles") or {}
    out += [c for c in brand.get("competitors", []) if not cp.get(c)]
    return out


def _valid(channel: str, url: str) -> bool:
    return any(d in url for d in CHANNEL_DOMAIN.get(channel, ()))


def discover(name: str, category_hint: str, ledger: RunLedger) -> list[dict]:
    """Candidate OfficialProfile dicts for one entity, or [] if nothing is found or confirmed."""
    query = f"{name} 공식 Instagram YouTube Facebook X 트위터 Threads 블로그 계정"
    try:
        res = ledger.call("perplexity", "official_accounts_search", {"name": name}, 0.005,
                          lambda: _search()([query], max_results=8), cache_days=7)
    except ProviderError:
        return []
    results = res.data["results"]
    if not results:
        return []
    listing = "\n".join(f"- {r['url']} :: {r['title']} :: {r['snippet'][:160]}" for r in results)
    user = f"<brand>{name}</brand>\n<category>{category_hint}</category>\n<search_results>\n{listing}\n</search_results>"
    try:
        ai = ledger.call("anthropic", "official_accounts_judge", {"name": name}, 0.01,
                         lambda: _structured()(SYSTEM, user, SCHEMA, max_tokens=800))
    except ProviderError:
        return []
    out, seen = [], set()
    for row in ai.data.get("profiles") or []:
        channel, url = row.get("channel"), (row.get("url") or "").strip()
        if channel not in CHANNELS or channel in seen or not url or not _valid(channel, url):
            continue
        seen.add(channel)
        out.append({"channel": channel, "url": url, "status": "candidate"})
    return out


def fill(cfg: dict, ledger: RunLedger) -> bool:
    """Add candidate accounts in place for every entity still missing them. True when it changed."""
    changed = False
    for b in cfg.get("brands", []):
        hint = ", ".join(b.get("categories", [])) or b["name"]
        for name in missing(b):
            found = discover(name, hint, ledger)
            if not found:
                continue
            if name == b["name"]:
                b["official_profiles"] = [*(b.get("official_profiles") or []), *found]
            else:
                cp = dict(b.get("competitor_profiles") or {})
                cp[name] = [*cp.get(name, []), *found]
                b["competitor_profiles"] = cp
            changed = True
    return changed
