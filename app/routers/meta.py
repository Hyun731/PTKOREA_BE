"""Static catalog the web uses: sections, channel support, profiles, style tokens."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.services.catalog import CHANNELS, DEFAULT_SLIDES, FRAMES, SECTIONS, channel_status
from core.composition.build import TEMPLATE_LABEL
from core.composition.tokens import tokens
from core.rendering.preview import backend as render_backend
from core.schemas.facts import MANUAL_METRICS

router = APIRouter()


@router.get("/meta")
def meta():
    return {
        # P0 UI shows only implemented profiles (PRD 3).
        "profiles": [{"id": "diagnostic", "label": "진단형 · 세션 1 활동 점검"}],
        "sections": SECTIONS,
        "frames": FRAMES,
        "default_slides": DEFAULT_SLIDES,
        "template_labels": TEMPLATE_LABEL,
        "channels": [{"id": cid, **c, "status": channel_status(c["provider"], bool(c["provider"]) and settings.provider_configured(c["provider"]))}
                     for cid, c in CHANNELS.items()],
        "providers": {p: settings.provider_configured(p) for p in ("perplexity", "anthropic", "scrapecreators", "apify", "naver")},
        "manual_metrics": list(MANUAL_METRICS),
        "render_backend": render_backend(),
        "tokens": tokens(),
    }
