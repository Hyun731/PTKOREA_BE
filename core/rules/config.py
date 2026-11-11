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
    r11_top_n: int
    r12_max_ratio: Decimal
    r12_min_creator_sample: int
    r13_gap_days: int
    # P1-2 파생 수치: 비율 Fact를 만들 최소 표본 수(작은 표본의 비율을 장표에 올리지 않는다).
    derived_min_n: int = 20
    # P2-2 쇼핑인사이트 성수기: 월 클릭 지수가 기간 평균의 이 배수 이상인 달
    shop_peak_lift: Decimal = Decimal("1.2")

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
            r11_top_n=int(raw["R11"]["top_n"]),
            r12_max_ratio=Decimal(raw["R12"]["max_ratio"]),
            r12_min_creator_sample=int(raw["R12"]["min_creator_sample"]),
            r13_gap_days=int(raw["R13"]["gap_days"]),
            derived_min_n=int(raw.get("derived", {}).get("min_n", 20)),
            shop_peak_lift=Decimal(raw.get("shopping", {}).get("peak_lift", "1.2")),
        )
