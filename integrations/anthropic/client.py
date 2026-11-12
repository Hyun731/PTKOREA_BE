"""Anthropic structured outputs for evidence extraction and lead writing (PRD 6, 10).

Our own JSON schema via output_config.format; references are our own IDs (no native
citations with strict JSON). Refusal fallbacks are enabled server-side by default.
Model id comes from ANTHROPIC_MODEL; never hard-coded.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from integrations.base import CallResult, ProviderError

# Published per-token prices (USD per 1M tokens), used to settle the ledger.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
          "claude-opus-5": (5.0, 25.0), "claude-fable-5-1": (10.0, 50.0)}


def model_id() -> str:
    m = os.environ.get("ANTHROPIC_MODEL")
    if not m or not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProviderError("PROVIDER_AUTH", "ANTHROPIC_API_KEY·ANTHROPIC_MODEL이 설정되지 않았습니다")
    return m


# 선별·분류처럼 판단이 단순한 호출은 저가 모델로 — ANTHROPIC_MODEL_LIGHT(기본 Haiku 5.5).
DEFAULT_LIGHT_MODEL = "claude-haiku-5-5"


def light_model_id() -> str:
    model_id()  # same key check
    return os.environ.get("ANTHROPIC_MODEL_LIGHT") or DEFAULT_LIGHT_MODEL


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=2, timeout=120.0)


# 구조화 출력이 받지 않는 제약(400 "property 'maxItems' is not supported"). 부르는 쪽이 개수·길이를
# 다시 자르므로, 보내기 전에 지워도 결과가 달라지지 않는다. minItems는 0·1만 받는다.
UNSUPPORTED_KEYS = ("maxItems", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
                    "exclusiveMaximum", "multipleOf")


def api_schema(schema: Any) -> Any:
    """서비스 모듈의 스키마를 API가 받는 꼴로 — 지원하지 않는 제약만 뺀 사본."""
    if isinstance(schema, list):
        return [api_schema(v) for v in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in UNSUPPORTED_KEYS or (k == "minItems" and isinstance(v, int) and v > 1):
            continue
        if k == "properties" and isinstance(v, dict):  # 속성 이름은 제약이 아니다 — 값만 다듬는다
            out[k] = {name: api_schema(sub) for name, sub in v.items()}
        else:
            out[k] = v if k in ("enum", "const", "required") else api_schema(v)
    return out


def image_media_type(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def user_content(user: str, images: Optional[list[bytes]] = None) -> Any:
    """글만 있으면 문자열 그대로, 이미지가 있으면 이미지 블록들 뒤에 글 — 알 수 없는 형식의 이미지는 뺀다."""
    if not images:
        return user
    import base64
    blocks: list[dict] = []
    for data in images:
        media = image_media_type(data)
        if media:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media,
                                                       "data": base64.b64encode(data).decode("ascii")}})
    return [*blocks, {"type": "text", "text": user}] if blocks else user


def structured(system: str, user: str, schema: dict, *, max_tokens: int = 8000, effort: str = "medium",
               client: Optional[Any] = None, images: Optional[list[bytes]] = None, light: bool = False) -> CallResult:
    """images: 글과 함께 볼 이미지(광고 소재 등) — 순서대로 붙고, 글에서 '이미지 n'으로 가리킨다.
    light: 관련성 선별·분류처럼 단순한 판단은 저가 모델로(서버 거절 대체(fallbacks)는 지원하지 않아 빼고 보낸다)."""
    import anthropic
    model = light_model_id() if light else model_id()
    c = client or _client()
    extra = {} if light else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        resp = c.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content(user, images)}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": api_schema(schema)}},
            **extra,
        )
    except anthropic.AuthenticationError:
        raise ProviderError("PROVIDER_AUTH", "Anthropic 키 인증 실패")
    except anthropic.PermissionDeniedError:
        raise ProviderError("PROVIDER_AUTH", "Anthropic 권한 오류 — 모델 접근 권한을 확인하세요")
    except anthropic.NotFoundError:
        raise ProviderError("PROVIDER_ERROR", f"모델 {model}을 찾을 수 없습니다")
    except anthropic.RateLimitError:
        raise ProviderError("RATE_LIMITED", "Anthropic 요청 한도 초과")
    except anthropic.BadRequestError as exc:
        raise ProviderError("PROVIDER_ERROR", f"Anthropic 요청 오류: {getattr(exc, 'message', '')[:200]}")
    except anthropic.APIStatusError as exc:
        raise ProviderError("PROVIDER_ERROR", f"Anthropic 오류 ({exc.status_code})")
    except anthropic.APIConnectionError:
        raise ProviderError("PROVIDER_ERROR", "Anthropic 연결 실패")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
             "model": getattr(resp, "model", model)}
    pin, pout = PRICES.get(usage["model"], PRICES.get(model, (4.0, 20.0)))
    cost = resp.usage.input_tokens / 1e6 * pin + resp.usage.output_tokens / 1e6 * pout
    if resp.stop_reason == "refusal":
        raise ProviderError("REFUSAL", "모델이 이 요청을 거절했습니다")
    if resp.stop_reason == "max_tokens":
        raise ProviderError("INVALID_RESPONSE", "응답이 길이 제한에서 잘렸습니다")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
    if text is None:
        raise ProviderError("INVALID_RESPONSE", "구조화 응답이 없습니다")
    try:
        data = json.loads(text)
    except ValueError:
        raise ProviderError("INVALID_RESPONSE", "JSON 응답을 해석할 수 없습니다")
    return CallResult(data=data, usage=usage, cost_usd=round(cost, 6), cost_is_estimate=False)
