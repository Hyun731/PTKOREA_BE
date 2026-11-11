"""P2-5 블로그 문서 유형 (core/ingestion/blog_types.py)."""
import json
from datetime import date

import pytest

from core.ingestion.blog_types import BLOG_TYPES, disclosure_markers, share_facts

TODAY = date(2026, 11, 11)


@pytest.mark.parametrize("text,expected", [
    ("이 포스팅은 업체로부터 제품을 무상으로 제공받아 작성되었습니다", ["sponsored"]),
    ("소정의 원고료를 지원받아 솔직하게 작성한 후기", ["sponsored"]),
    ("#협찬 #샘소나이트", ["sponsored"]),
    ("이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.", ["affiliate"]),
    ("쿠팡에서 브라이튼 레톤 여행가방 캐리어 구매하고 더 많은 혜택을 받으세요!", ["affiliate"]),
    ("체험단으로 받았고 최저가 링크는 아래에", ["sponsored", "affiliate"]),
    ("작년에 내 돈 주고 산 캐리어 3년 써 본 후기", []),
])
def test_disclosure_markers(text, expected):
    assert disclosure_markers(text) == expected


def _docs(counts: dict) -> list[dict]:
    out = []
    for t, k in counts.items():
        out += [{"url": f"https://blog.naver.com/{t}/{i}", "type": t} for i in range(k)]
    return out


def test_share_facts_cover_every_type_and_sum_to_100():
    docs = _docs({"real_use": 7, "sponsored": 9, "shopping_affiliate": 11, "promo_template": 3})
    facts = share_facts(brand_id="SO", entity="샘소나이트", keyword="샘소나이트 캐리어", docs=docs, measured_at=TODAY, min_n=20)
    assert [f.dims["type"] for f in facts] == list(BLOG_TYPES)
    by = {f.dims["type"]: f for f in facts}
    assert str(by["shopping_affiliate"].value) == "36.7" and str(by["other"].value) == "0.0"
    assert all(f.metric == "blog_type_share" and f.unit == "percent" and f.dims["n"] == "30" for f in facts)
    assert all(f.verification_status == "candidate" for f in facts)
    assert len(json.loads(by["sponsored"].source_locator)) == 9 and json.loads(by["other"].source_locator) == []
    assert "블로그 상위 30건 중 쇼핑·제휴" in by["shopping_affiliate"].label
    again = share_facts(brand_id="SO", entity="샘소나이트", keyword="샘소나이트 캐리어", docs=docs, measured_at=TODAY, min_n=20)
    assert [f.id for f in again] == [f.id for f in facts]


def test_share_facts_skip_thin_samples_and_unknown_types():
    docs = _docs({"real_use": 10}) + [{"url": "x", "type": "nonsense"}] * 15
    assert share_facts(brand_id="SO", entity="샘소나이트", keyword="샘소나이트", docs=docs, measured_at=TODAY, min_n=20) == []
