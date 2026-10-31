"""Other spellings of brand names (한글·영문·흔한 오기), filled in by the AI where none are set.

Articles often name a brand only one way — 'Matin Kim' for 마땡킴, '샘소나이트' for 쌤소나이트 — so a
search result that never uses the configured spelling would be dropped as not about the brand. The
AI proposes names that refer to that brand only; generic words are not accepted.
"""
from __future__ import annotations

import re
from typing import Callable

from app.services.ledger import RunLedger

SYSTEM = """당신은 한국 시장의 브랜드 이름을 잘 아는 리서처입니다. <brands>의 각 브랜드가 기사·SNS에서 달리 불리는 이름을 찾습니다.
- 공식 영문명, 한글 표기, 흔한 다른 표기(예: 쌤소나이트 ↔ 샘소나이트), 띄어쓰기 변형만 넣습니다.
- 그 브랜드만 가리키는 이름이어야 합니다. 일반 명사, 제품 종류, 모회사·다른 브랜드 이름은 넣지 않습니다.
- 확실하지 않으면 빈 배열로 둡니다. 브랜드마다 최대 4개."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["brands"], "properties": {"brands": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "aliases"],
                               "properties": {"name": {"type": "string"},
                                              "aliases": {"type": "array", "items": {"type": "string"}}}}}}}

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def _key(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def missing(cfg: dict) -> list[str]:
    """Brand, competitor and benchmark names the AI has not been asked about yet."""
    out: list[str] = []
    for b in cfg.get("brands", []):
        ent = b.get("entity_aliases") or {}
        out += [n for n in [b["name"], *b.get("competitors", []), *b.get("benchmarks", [])] if n not in ent]
    return list(dict.fromkeys(out))


def suggest(names: list[str], category_hint: str, ledger: RunLedger) -> dict[str, list[str]]:
    if not names:
        return {}
    user = f"<category>{category_hint}</category>\n<brands>\n" + "\n".join(names) + "\n</brands>"
    res = ledger.call("anthropic", "brand_aliases", {"names": names, "hint": category_hint}, 0.01,
                      lambda: _structured()(SYSTEM, user, SCHEMA, max_tokens=2000))
    taken = {_key(n) for n in names}
    out: dict[str, list[str]] = {}
    for row in res.data.get("brands") or []:
        name = row.get("name")
        if name not in names:
            continue
        keep = []
        for a in row.get("aliases") or []:
            a = a.strip()
            # Never another listed brand's name, never the name itself, never a one-letter token.
            if len(_key(a)) >= 2 and _key(a) != _key(name) and _key(a) not in taken - {_key(name)}:
                keep.append(a[:40])
        # RIMOWA and Rimowa match the same articles: keep one of each.
        out[name] = list({_key(a): a for a in reversed(keep)}.values())[::-1][:4]
    return out


def fill(cfg: dict, ledger: RunLedger) -> bool:
    """Fill missing spellings into a project config in place. True when the config changed."""
    names = missing(cfg)
    if not names:
        return False
    hint = ", ".join(dict.fromkeys(c for b in cfg.get("brands", []) for c in b.get("categories", []))) or "브랜드"
    found = suggest(names, hint, ledger)
    for b in cfg.get("brands", []):
        ent = dict(b.get("entity_aliases") or {})
        for n in [b["name"], *b.get("competitors", []), *b.get("benchmarks", [])]:
            if n in ent:
                continue
            if n == b["name"]:  # the brand's own spellings stay in `aliases`, which other steps also read
                b["aliases"] = b.get("aliases") or found.get(n, [])
                ent[n] = []  # an empty list records that it was asked
            else:
                ent[n] = found.get(n, [])
        b["entity_aliases"] = ent
    return True
