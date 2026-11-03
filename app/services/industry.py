"""Industry per brand, filled in by the AI where none is set (Phase 1-1 브랜드 카드).

The planner types the brand name and nothing else; the AI picks the closest industry from the
fixed list so defaults (review-centric vs metric-centric scope items, Phase 2) can follow it.
Never overwrites a value the planner already set.
"""
from __future__ import annotations

from typing import Callable

from app.services.ledger import RunLedger
from core.schemas.project import INDUSTRIES

SYSTEM = f"""당신은 한국 소비재·서비스 시장을 잘 아는 리서처입니다. <brands>의 각 브랜드에 가장 맞는 업종을 고릅니다.
- 업종은 반드시 다음 목록 중 하나: {', '.join(INDUSTRIES)}.
- 확실하지 않으면 '기타'를 고릅니다."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brands"], "properties": {"brands": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "industry"],
                               "properties": {"name": {"type": "string"},
                                              "industry": {"type": "string", "enum": list(INDUSTRIES)}}}}}}

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def missing(cfg: dict) -> list[str]:
    """Brand names that have no industry set yet."""
    return [b["name"] for b in cfg.get("brands", []) if not b.get("industry")]


def suggest(names: list[str], category_hint: str, ledger: RunLedger) -> dict[str, str]:
    if not names:
        return {}
    user = f"<category>{category_hint}</category>\n<brands>\n" + "\n".join(names) + "\n</brands>"
    res = ledger.call("anthropic", "brand_industry", {"names": names, "hint": category_hint}, 0.01,
                      lambda: _structured()(SYSTEM, user, SCHEMA, max_tokens=800))
    out: dict[str, str] = {}
    for row in res.data.get("brands") or []:
        name, industry = row.get("name"), row.get("industry")
        if name in names and industry in INDUSTRIES:
            out[name] = industry
    return out


def fill(cfg: dict, ledger: RunLedger) -> bool:
    """Fill missing industries into a project config in place. True when the config changed."""
    names = missing(cfg)
    if not names:
        return False
    hint = ", ".join(dict.fromkeys(c for b in cfg.get("brands", []) for c in b.get("categories", []))) or "브랜드"
    found = suggest(names, hint, ledger)
    if not found:
        return False
    changed = False
    for b in cfg.get("brands", []):
        if not b.get("industry") and b["name"] in found:
            b["industry"] = found[b["name"]]
            changed = True
    return changed
