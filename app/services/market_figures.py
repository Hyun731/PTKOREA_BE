"""시장·정책·업종 KPI 수치를 Fact로 (IMPROVEMENT_PLAN P4-1).

시장 자료를 추출할 때 AI가 `figures`(지표, 값, 단위, 기간, 범위, 원문 문장)를 함께 돌려준다. 원문 문장이 페이지에
글자 그대로 있고 그 문장에 값이 들어 있을 때만 Fact 후보(verification_status=candidate)로 저장한다. 자료를 채택하면
그 자료의 후보 수치도 함께 채택된다(app/services/adopt.py, FactRow.material_id).

Fact 계약 (core/composition/axes.py MK1이 읽는다)
- metric: market_size(시장 규모) · market_cagr(연평균 성장률) · macro_indicator(거시 지표) · industry_kpi(업종 KPI)
- unit: krw · usd · percent · count · people, period_start~period_end: 수치의 기준 기간
- dims: segment(시장 범위) · indicator(지표 이름) · quote(원문 문장, 300자)
- entity: 조사 대상(시장 조사는 카테고리), evidence_id: 자료, source_id: 출처

정부 통계는 한국관광공사·통계청·관세청 등의 보도자료를 Perplexity로 찾아 같은 추출을 거친다(`gov_queries`).
장표 출처는 보도자료 제목과 날짜로 표시한다(axes._source_name).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from core.decimalx import canonical_decimal
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.industry_profiles import INDUSTRY_PROFILES
from core.schemas.facts import Fact

FIGURE_METRICS = ["market_size", "market_cagr", "macro_indicator", "industry_kpi"]
FIGURE_UNITS = ["krw", "usd", "percent", "count", "people"]
FIGURE_SECTIONS = ("market", "market_kpi")
MAX_FIGURES = 8

FIGURES_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["metric", "name", "value", "unit", "period", "segment", "quote"],
    "properties": {"metric": {"type": "string", "enum": FIGURE_METRICS}, "name": {"type": "string"},
                   "value": {"type": "string"}, "unit": {"type": "string", "enum": FIGURE_UNITS},
                   "period": {"type": "string"}, "segment": {"type": "string"}, "quote": {"type": "string"}}}}

FIGURES_PROMPT = """- figures: 사용자 메시지에 '수치 추출: 사용'이 있을 때만 씁니다(그 외에는 빈 배열). 원문에 숫자로 나온 시장·정책·업종 지표를 최대 8개.
  metric: "market_size"(시장 규모·거래액), "market_cagr"(연평균 성장률·CAGR), "macro_indicator"(출입국자 수·관광객 수·수입액 같은 거시 지표), "industry_kpi"(그 밖의 업종 지표).
  name: 지표 이름(예: "국민 해외관광객 수", "국내 러기지 시장 규모"). 기간(연·월)은 name이 아니라 period에 씁니다 — 같은 지표는 기간이 달라도 같은 name. value: 원문 숫자를 쉼표 없이 그대로(단위 변환·추정 금지 — '억', '백만', 'million' 같은 단위는 서버가 원문에서 읽습니다).
  unit: "krw"(원), "usd"(달러), "percent"(%), "people"(명), "count"(그 밖의 개수).
  period: 수치의 기준 기간 — "2025", "2025-06", "2026-01~2026-08", "2026~2031" 형식. 원문에 기간이 없으면 빈 문자열.
  segment: 시장 범위(예: "국내", "글로벌 러기지", "프리미엄 캐리어"), 없으면 빈 문자열.
  quote: 그 숫자가 들어 있는 원문 문장을 글자 그대로 복사.
  목표·계획치, 다른 나라·다른 업종 수치는 넣지 않습니다."""

UNIT_SCALE = {"조": 12, "천억": 11, "백억": 10, "십억": 9, "억": 8, "천만": 7, "백만": 6, "십만": 5, "만": 4, "천": 3,
              "trillion": 12, "billion": 9, "million": 6}
UNIT_SCALE = {k: Decimal(10) ** v for k, v in UNIT_SCALE.items()}
SCALE_WORD = re.compile(r"\s*(" + "|".join(sorted(UNIT_SCALE, key=len, reverse=True)) + ")", re.I)
PERIOD = re.compile(r"^(\d{4})(?:[-.](\d{1,2}))?(?:\s*[~\-–]\s*(\d{4})(?:[-.](\d{1,2}))?)?$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _digits(s: str) -> str:
    return re.sub(r"[,\s]", "", s or "")


def _month_end(y: int, m: int) -> date:
    first_of_next = date(y + (m == 12), m % 12 + 1, 1)
    return date.fromordinal(first_of_next.toordinal() - 1)


def parse_period(text: str) -> Optional[tuple[date, date]]:
    """'2025' / '2025-06' / '2026-01~2026-08' / '2026~2031' -> (first day, last day)."""
    m = PERIOD.match(_norm(text))
    if not m:
        return None
    y1, m1, y2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        start = date(int(y1), int(m1 or 1), 1)
        if y2:
            end = _month_end(int(y2), int(m2)) if m2 else date(int(y2), 12, 31)
        else:
            end = _month_end(int(y1), int(m1)) if m1 else date(int(y1), 12, 31)
    except ValueError:
        return None
    return (start, end) if start <= end else None


def validate_figures(data: dict, page_text: str) -> tuple[list[dict], list[str]]:
    """Figures whose quote is verbatim in the page and holds the value; a '2,958만명'-style number is scaled."""
    text = _norm(page_text)
    out, issues = [], []
    for i, f in enumerate((data.get("figures") or [])[:MAX_FIGURES], start=1):
        quote = _norm(f.get("quote", ""))
        raw = _digits(str(f.get("value", "")))
        try:
            value = Decimal(raw)
        except InvalidOperation:
            issues.append(f"시장 수치 {i}: 숫자가 아님")
            continue
        if not quote or quote not in text:
            issues.append(f"시장 수치 {i}: 원문 인용 불일치")
            continue
        if not raw or raw not in _digits(quote):
            issues.append(f"시장 수치 {i}: 인용문에 값이 없음")
            continue
        if f.get("metric") not in FIGURE_METRICS or f.get("unit") not in FIGURE_UNITS or value < 0:
            issues.append(f"시장 수치 {i}: 지표·단위 오류")
            continue
        if f["unit"] != "percent":
            # the number as printed ('2,958만명', '18,617백만 달러', 'USD 18.6 billion') -> its full value
            scale = re.search(re.escape(raw).replace(r"\.", r"[.,]?") + SCALE_WORD.pattern, _digits(quote), re.I)
            if scale:
                value *= UNIT_SCALE[scale.group(1).lower()]
        if f["unit"] in ("people", "count") and value != value.to_integral_value():
            issues.append(f"시장 수치 {i}: 사람 수·개수가 정수가 아님")
            continue
        out.append({"metric": f["metric"], "name": _norm(f.get("name", ""))[:80] or "시장 수치", "value": value,
                    "unit": f["unit"], "period": parse_period(f.get("period", "")),
                    "segment": _norm(f.get("segment", ""))[:60], "quote": quote})
    return out, issues


def make_figure_fact(fig: dict, *, brand_id: str, entity: str, measured_at: date, source: str,
                     source_id: Optional[str], evidence_id: Optional[str], url: Optional[str]) -> Fact:
    start, end = fig["period"] or (measured_at, measured_at)
    dims = {"quote": fig["quote"][:300]}
    if fig["segment"]:
        dims["segment"] = fig["segment"]
    if fig["metric"] in ("macro_indicator", "industry_kpi"):
        dims["indicator"] = fig["name"]
    payload = {"brand": brand_id, "entity": entity, "metric": fig["metric"], "value": canonical_decimal(fig["value"]),
               "unit": fig["unit"], "period": f"{start}~{end}", "source_id": source_id, "evidence_id": evidence_id,
               "dims": {k: v for k, v in dims.items() if k != "quote"}}
    h = content_hash(payload)
    return Fact(id=fact_id_from_hash(h), content_hash=h, brand_id=brand_id, entity=entity, metric=fig["metric"],
                value=fig["value"], unit=fig["unit"], dims=dims, period_start=start, period_end=end,
                measured_at=measured_at, source=source, source_id=source_id, evidence_id=evidence_id, url=url,
                method="원문 문장과 대조한 AI 추출 수치", confidence="verified", verification_status="candidate",
                label=fig["name"])


# Profile gov_stats entries that name a collector module rather than a search phrase (P4-2 turns them into phrases).
GOV_PRESS = {
    "immigration_arrivals": "한국관광공사 국민 해외관광객 출국자 수 보도자료",
    "한국관광공사 출입국 통계": "한국관광공사 국민 해외관광객 출국자 수 보도자료",
}
GOV_DEFAULT = "{cat} 통계청 관세청 보도자료"


def gov_queries(industry: Optional[str], cat: str, year) -> list[str]:
    """One or two press-release searches for the government statistics of this brand's industry."""
    profile = INDUSTRY_PROFILES.get(industry or "")
    phrases = []
    for g in (profile.gov_stats if profile else ()):
        phrase = GOV_PRESS.get(g, g)
        if phrase:
            phrases.append(phrase if "보도자료" in phrase else f"{phrase} 보도자료")
    phrases = phrases or [GOV_DEFAULT.format(cat=cat)]
    return [f"{p} {year}".strip() for p in phrases[:2]]


def adopt_figures(db, m) -> int:
    """Accepting a market card accepts the figures read from it (they were checked against its own words)."""
    from sqlalchemy import select

    from app.models import FactRow
    n = 0
    for row in db.scalars(select(FactRow).where(FactRow.material_id == m.id, FactRow.verification_status == "candidate",
                                                FactRow.origin == "auto", FactRow.superseded_by.is_(None))):
        if (row.data or {}).get("metric") in FIGURE_METRICS:
            row.verification_status = "eligible"
            n += 1
    return n
