"""Per-run usage ledger and response cache (PRD 13; DEVELOPMENT_PLAN 9 초기 설정과 비용 관리).

Every paid call is reserved before it starts and settled after, so the project total stays exact.
RUN_BUDGET_USD is an optional per-run cap; unset means no cap (cost is reported, not gated).
A cached response is reused at zero cost, so retrying a run never re-bills finished work.
A call whose outcome is unknown (timeout) keeps its estimated cost as `unknown`.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import timedelta
from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProviderCache, ProviderCall, utcnow
from integrations.base import CallResult, ProviderError

SCHEMA_VERSION = "1"
# Budget check + reservation must be one step when several workers share a run (parallel research).
_BUDGET_LOCK = threading.Lock()


def run_budget_usd() -> float:
    try:
        return float(os.environ.get("RUN_BUDGET_USD") or 0)
    except ValueError:
        return 0.0


def cache_key(provider: str, endpoint: str, request: Any) -> str:
    text = json.dumps({"p": provider, "e": endpoint, "r": request, "v": SCHEMA_VERSION}, sort_keys=True,
                      ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RunLedger:
    """Thread-safe: every call uses its own short session, so parallel workers of one run can share it."""

    def __init__(self, db: Session, project_id: str, job_id: Optional[str], budget_usd: Optional[float] = None):
        self.db, self.project_id, self.job_id = db, project_id, job_id
        self._bind = db.get_bind()
        self.budget = run_budget_usd() if budget_usd is None else budget_usd  # 0 = no cap

    def _session(self) -> Session:
        return Session(bind=self._bind, expire_on_commit=False)

    def spent(self, s: Optional[Session] = None) -> float:
        own = s is None
        s = s or self._session()
        try:
            q = select(func.coalesce(func.sum(ProviderCall.cost_usd), 0.0)).where(
                ProviderCall.job_id == self.job_id, ProviderCall.status.in_(("settled", "unknown", "reserved")))
            reserved = select(func.coalesce(func.sum(ProviderCall.est_cost_usd), 0.0)).where(
                ProviderCall.job_id == self.job_id, ProviderCall.status == "reserved")
            return float(s.scalar(q) or 0) + float(s.scalar(reserved) or 0)
        finally:
            if own:
                s.close()

    def call(self, provider: str, endpoint: str, request: Any, est_cost: float, fn: Callable[[], CallResult],
             cache_days: Optional[int] = 7) -> CallResult:
        key = cache_key(provider, endpoint, request)
        s = self._session()
        try:
            if cache_days is not None:
                hit = s.get(ProviderCache, key)
                if hit and hit.created_at.replace(tzinfo=hit.created_at.tzinfo or utcnow().tzinfo) > utcnow() - timedelta(days=cache_days):
                    s.add(ProviderCall(project_id=self.project_id, job_id=self.job_id, provider=provider, endpoint=endpoint,
                                       fingerprint=key, status="cache_hit", usage=hit.usage, finished_at=utcnow()))
                    s.commit()
                    return CallResult(data=hit.data, usage=hit.usage, cost_usd=0.0, cost_is_estimate=False, cached=True)
            with _BUDGET_LOCK:
                if self.budget > 0 and self.spent(s) + est_cost > self.budget:
                    raise ProviderError("BUDGET_EXCEEDED", f"실행 예산 ${self.budget:.2f}에 도달해 남은 호출을 멈췄습니다")
                row = ProviderCall(project_id=self.project_id, job_id=self.job_id, provider=provider, endpoint=endpoint,
                                   fingerprint=key, status="reserved", est_cost_usd=est_cost)
                s.add(row)
                s.commit()
            try:
                result = fn()  # the slow network call runs outside the lock
            except ProviderError as exc:
                row.status = "unknown" if exc.code == "TIMEOUT" else "failed"
                row.cost_usd = est_cost if exc.code == "TIMEOUT" else 0.0
                row.error_code, row.finished_at = exc.code, utcnow()
                s.commit()
                raise
            row.status, row.cost_usd, row.cost_is_estimate = "settled", result.cost_usd, result.cost_is_estimate
            row.usage, row.finished_at = result.usage, utcnow()
            if cache_days is not None:
                existing = s.get(ProviderCache, key)
                if existing:
                    existing.data, existing.usage, existing.created_at = result.data, result.usage, utcnow()
                else:
                    s.add(ProviderCache(key=key, provider=provider, data=result.data, usage=result.usage))
            s.commit()
            return result
        finally:
            s.close()


def usage_summary(db: Session, project_id: str) -> dict:
    rows = list(db.scalars(select(ProviderCall).where(ProviderCall.project_id == project_id)))
    by: dict[str, dict] = {}
    for r in rows:
        b = by.setdefault(r.provider, {"calls": 0, "cache_hits": 0, "failed": 0, "cost_usd": 0.0, "estimated": False})
        if r.status == "cache_hit":
            b["cache_hits"] += 1
            continue
        b["calls"] += 1
        b["failed"] += r.status == "failed"
        b["cost_usd"] += r.cost_usd
        b["estimated"] = b["estimated"] or r.cost_is_estimate
    total = sum(b["cost_usd"] for b in by.values())
    return {"budget_per_run_usd": run_budget_usd(), "total_cost_usd": round(total, 4),
            "providers": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in by.items()}}
