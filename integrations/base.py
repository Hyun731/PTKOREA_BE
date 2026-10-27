"""Shared provider plumbing (PRD 13 실행과 비용, 14 보안).

- Only 429 / transient 5xx are retried, at most twice, with exponential backoff + jitter.
- 401 / 402 / 403 are never retried automatically.
- Errors are typed so the job can say what happened without leaking keys or tracebacks.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    """code: PROVIDER_AUTH | QUOTA_EXCEEDED | SOURCE_UNAVAILABLE | RATE_LIMITED | PROVIDER_ERROR |
    TIMEOUT | BUDGET_EXCEEDED | BLOCKED_URL | REFUSAL | INVALID_RESPONSE"""

    def __init__(self, code: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class CallResult:
    data: Any
    usage: dict = field(default_factory=dict)  # provider-reported units (credits, tokens…)
    cost_usd: float = 0.0
    cost_is_estimate: bool = True
    cached: bool = False


def _classify(status: int, provider: str) -> ProviderError:
    if status in (401, 403):
        return ProviderError("PROVIDER_AUTH", f"{provider} 인증·권한 오류 — 키를 확인하세요", status)
    if status == 402:
        return ProviderError("QUOTA_EXCEEDED", f"{provider} 크레딧·결제 한도 초과", status)
    if status == 404:
        return ProviderError("SOURCE_UNAVAILABLE", f"{provider}에서 대상을 찾을 수 없습니다", status)
    if status == 429:
        return ProviderError("RATE_LIMITED", f"{provider} 요청 한도 초과 — 잠시 후 다시 시도", status)
    return ProviderError("PROVIDER_ERROR", f"{provider} 오류 ({status})", status)


def request_json(provider: str, method: str, url: str, *, headers: dict, params: Optional[dict] = None,
                 json_body: Optional[dict] = None, timeout: float = 45.0, max_retries: int = 2,
                 transport: Optional[httpx.BaseTransport] = None) -> Any:
    last: Optional[ProviderError] = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout, transport=transport) as client:
                resp = client.request(method, url, headers=headers, params=params, json=json_body)
        except httpx.TimeoutException:
            # An unknown outcome on a paid call is not retried blindly (PRD 13).
            raise ProviderError("TIMEOUT", f"{provider} 응답 시간 초과")
        except httpx.HTTPError as exc:
            raise ProviderError("PROVIDER_ERROR", f"{provider} 연결 실패: {type(exc).__name__}")
        if resp.status_code < 400:
            try:
                return resp.json()
            except ValueError:
                raise ProviderError("INVALID_RESPONSE", f"{provider} 응답을 해석할 수 없습니다")
        last = _classify(resp.status_code, provider)
        if resp.status_code not in RETRY_STATUSES or attempt == max_retries:
            raise last
        retry_after = resp.headers.get("retry-after")
        delay = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 2 ** attempt
        time.sleep(min(30.0, delay) + random.uniform(0, 0.5))
    raise last or ProviderError("PROVIDER_ERROR", f"{provider} 알 수 없는 오류")
