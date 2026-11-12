"""Static catalog the web uses: sections, channel support, profiles, style tokens."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.services import official_accounts, scope
from app.services.catalog import CHANNELS, DEFAULT_SLIDES, FRAMES, SECTIONS, channel_status
from core.composition.build import TEMPLATE_LABEL
from core.composition.tokens import tokens
from core.rendering.preview import backend as render_backend
from core.schemas.facts import MANUAL_METRICS
from core.industry_profiles import INDUSTRY_PROFILES
from core.schemas.project import INDUSTRIES, INDUSTRY_TYPES, REQUIRED_REVIEW_INDUSTRIES

router = APIRouter()


@router.get("/meta")
def meta():
    return {
        # P0 UI shows only implemented profiles (PRD 3).
        "profiles": [{"id": "diagnostic", "label": "진단형 · 세션 1 활동 점검"}],
        "sections": SECTIONS,
        "scope": scope.catalog(),
        "frames": FRAMES,
        "default_slides": DEFAULT_SLIDES,
        "template_labels": TEMPLATE_LABEL,
        "channels": [{"id": cid, **c, "status": channel_status(c["provider"], bool(c["provider"]) and settings.provider_configured(c["provider"]))}
                     for cid, c in CHANNELS.items()],
        "providers": {p: settings.provider_configured(p) for p in ("perplexity", "anthropic", "scrapecreators", "apify", "naver")},
        "manual_metrics": list(MANUAL_METRICS),
        "render_backend": render_backend(),
        "tokens": tokens(),
        "industries": [{"id": i, "types": list(INDUSTRY_TYPES.get(i, ())), "review_required": i in REQUIRED_REVIEW_INDUSTRIES,
                        # 피드백 #1(업종별 variation): 확인된 프로필이 있으면 키워드 힌트가 코드로 이미 확정돼
                        # 있어, 브랜드별 후보 확인 UI가 필요 없다(검토 전 AI 초안은 후보로 나간다).
                        "has_keyword_profile": bool(INDUSTRY_PROFILES.get(i) and INDUSTRY_PROFILES[i].reviewed)}
                       for i in INDUSTRIES],
        "official_channels": [{"id": c, "label": official_accounts.CHANNEL_LABEL[c],
                               "auto_collect": c in official_accounts.AUTO_COLLECTABLE,
                               "tier": official_accounts.CHANNEL_TIER.get(c, "secondary")}
                              for c in official_accounts.CHANNELS],
    }
