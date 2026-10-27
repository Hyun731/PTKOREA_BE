"""Fact registry with deterministic DerivedFact IDs (PRD 8 Fact ID, PRD 9 derived rules)."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional, Union

from core.decimalx import canonical_decimal
from core.schemas.facts import DerivedFact, DerivedValue, Fact

AnyFact = Union[Fact, DerivedFact]


class MissingParentError(ValueError):
    """A missing parent stops the calculation (PRD 9)."""


def _canon(v: Any) -> Any:
    if isinstance(v, Decimal):
        return canonical_decimal(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


class FactRegistry:
    def __init__(self, facts: Iterable[Fact] = ()):
        self.facts: dict[str, Fact] = {}
        self.derived: dict[str, DerivedFact] = {}
        for f in facts:
            self.facts[f.id] = f

    def get(self, fact_id: str) -> Optional[AnyFact]:
        return self.facts.get(fact_id) or self.derived.get(fact_id)

    def __contains__(self, fact_id: str) -> bool:
        return fact_id in self.facts or fact_id in self.derived

    def _span(self, parent: AnyFact) -> Optional[tuple[date, date]]:
        if isinstance(parent, Fact):
            return (parent.measured_at, parent.measured_at)
        return parent.observation_span

    def derive(
        self,
        formula_id: str,
        parents: list[str],
        *,
        brand_id: str,
        metric: str,
        value: DerivedValue,
        unit: str,
        entity: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        version: str = "1",
        partial: bool = False,
        definition: Optional[str] = None,
    ) -> DerivedFact:
        params = params or {}
        parent_ids = sorted(set(parents))
        objs = []
        for pid in parent_ids:
            p = self.get(pid)
            if p is None:
                raise MissingParentError(f"{formula_id}: 부모 {pid} 없음")
            if p.confidence == "missing":
                raise MissingParentError(f"{formula_id}: missing 부모 {pid}")
            objs.append(p)
        key = json.dumps(
            {"f": formula_id, "v": version, "p": _canon(params), "parents": parent_ids, "entity": entity, "metric": metric},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        did = "DF-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        spans = [s for s in (self._span(o) for o in objs) if s]
        span = (min(s[0] for s in spans), max(s[1] for s in spans)) if spans else None
        confidence = "estimated" if any(o.confidence == "estimated" for o in objs) else "verified"
        df = DerivedFact(
            id=did, formula_id=formula_id, formula_version=version, derived_from=parent_ids,
            parameters=_canon(params), brand_id=brand_id, entity=entity, metric=metric, value=value,
            unit=unit, measured_at=span[1] if span else None, observation_span=span,
            confidence=confidence, partial=partial, definition=definition,
        )
        self.derived[did] = df
        return df

    def lineage(self, fact_id: str) -> list[str]:
        """All raw Fact IDs a value traces back to."""
        out: list[str] = []
        stack = [fact_id]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur in self.facts:
                out.append(cur)
            elif cur in self.derived:
                stack.extend(self.derived[cur].derived_from)
        return sorted(out)
