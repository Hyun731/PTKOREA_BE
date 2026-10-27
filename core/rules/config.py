"""rules_config loader (PRD 9: all thresholds in rules_config)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path(__file__).with_name("rules_config.json")


@dataclass(frozen=True)
class RulesConfig:
    version: str
    ad_like_view_threshold: Decimal
    long_window: str
    main_window: str
    r03_min_months: int
    r04_min_reduction: Decimal
    r05_max_self_ratio: Decimal
    r10_min_ad_share: Decimal
    r10_min_coverage: Decimal
    r10_min_view_posts: int

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "RulesConfig":
        raw = json.loads((path or DEFAULT_PATH).read_text(encoding="utf-8"))
        return cls(
            version=raw["version"],
            ad_like_view_threshold=Decimal(raw["ad_like_view_threshold"]),
            long_window=raw["windows"]["long"],
            main_window=raw["windows"]["main"],
            r03_min_months=int(raw["R03"]["min_months"]),
            r04_min_reduction=Decimal(raw["R04"]["min_reduction_pp"]),
            r05_max_self_ratio=Decimal(raw["R05"]["max_self_ratio"]),
            r10_min_ad_share=Decimal(raw["R10"]["min_ad_share"]),
            r10_min_coverage=Decimal(raw["R10"]["min_coverage"]),
            r10_min_view_posts=int(raw["R10"]["min_view_posts"]),
        )
