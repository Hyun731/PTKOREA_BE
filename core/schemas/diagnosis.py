"""브랜드 진단(IMPROVEMENT_PLAN P5-1): 진단 플래너가 쓰고 진단 템플릿(P5-2)이 읽는 형식.

AI 답은 서버 검증(app.services.diagnosis)을 거친 뒤에만 이 형식으로 저장된다. 그래서 여기 있는 id는
모두 그때 채택된 자료(Fact·소비자 원문)에 있던 것이다. 문장 안의 숫자는 Paragraph의 fact part로만 들어가며
(원칙: 숫자는 Fact로만), 장표를 만들 때 값이 다시 포맷된다. 자료가 바뀌어 사라진 id는 템플릿이 건너뛴다.

저장(`projects.diagnosis`)은 자사 브랜드마다 버전을 쌓는다:
    {brand_id: {"active": 3, "versions": [DiagnosisVersion, ...]}}
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.schemas.slidespec import Paragraph

STAGES = ("인지", "고려", "탐색", "구매", "검증")  # 구매 퍼널 5단계(D1 화살표 머리 순서)
STATUSES = ("강점", "이탈", "보통")
PILLARS = ("소셜", "인플루언서", "콘텐츠")
CHART_TYPES = ("bar", "column", "stacked", "line")
KIND_LABEL = {"strength": "강점", "weakness": "약점"}

Stage = Literal["인지", "고려", "탐색", "구매", "검증"]
ChartType = Literal["bar", "column", "stacked", "line"]


class FunnelStage(BaseModel):
    stage: Stage
    fact_id: Optional[str] = None  # 그 단계를 말해 주는 대표 수치(D1 큰 숫자)
    label: str = ""  # 큰 숫자 아래 짧은 설명(예: '브랜드명 검색 점유')
    status: Literal["강점", "이탈", "보통"] = "보통"


class DiagnosisChart(BaseModel):
    type: ChartType
    fact_ids: list[str] = Field(default_factory=list)


class DiagnosisClaim(BaseModel):
    """강점·약점 하나 = D2 한 장: 주장 한 줄 + 근거 1~2줄(헤드라인 v2), 차트, 원문 카드."""
    id: str  # 버전 안에서 고정(c1, c2 …) — 빼기·고치기가 가리키는 이름
    kind: Literal["strength", "weakness"]
    claim: list[Paragraph] = Field(default_factory=list)
    evidence: list[Paragraph] = Field(default_factory=list)
    chart: Optional[DiagnosisChart] = None
    quote_material_ids: list[str] = Field(default_factory=list)
    excluded: bool = False  # 사람이 뺀 주장: 남겨 두되 장표에는 쓰지 않는다
    edited: bool = False  # 사람이 문장을 고친 주장


class CdjRow(BaseModel):
    """CDJ(고객 의사결정 여정) 한 단계 — D4 표 한 줄."""
    stage: str
    touchpoint: str = ""
    state: str = ""
    activity: str = ""


class Proposal(BaseModel):
    """활동 제안 하나 — D5 카드 한 장. 근거 수치가 없는 제안은 저장되지 않는다."""
    pillar: Literal["소셜", "인플루언서", "콘텐츠"]
    title: str
    cdj_stage: Optional[str] = None
    basis_fact_ids: list[str] = Field(default_factory=list)
    basis: list[Paragraph] = Field(default_factory=list)  # 근거 한 줄(수치는 fact part)


class Diagnosis(BaseModel):
    profile: str = ""  # 브랜드 한 줄 진단(간지·D1 리드)
    funnel: list[FunnelStage] = Field(default_factory=list)
    claims: list[DiagnosisClaim] = Field(default_factory=list)
    cdj: list[CdjRow] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)

    def shown_claims(self, kind: Optional[str] = None) -> list[DiagnosisClaim]:
        """장표에 쓰는 주장(사람이 뺀 것 제외), 강점 먼저."""
        out = [c for c in self.claims if not c.excluded and (kind is None or c.kind == kind)]
        return sorted(out, key=lambda c: 0 if c.kind == "strength" else 1)


class DiagnosisVersion(BaseModel):
    version: int
    fp: str = ""  # 진단 입력(채택 자료 목록)의 fingerprint — 같으면 다시 쓰지 않는다
    origin: Literal["auto", "rewrite", "edit", "restore"] = "auto"
    instruction: str = ""
    data: Diagnosis = Field(default_factory=Diagnosis)
    dropped: list[str] = Field(default_factory=list)  # 서버 검증에서 뺀 항목과 이유
    created_at: Optional[str] = None
    by: str = "ai"


def active_data(stored: Optional[dict]) -> dict[str, dict]:
    """`projects.diagnosis` → {brand_id: 활성 버전의 data(dict)} — 장표 구성(BuildInputs.diagnosis)용."""
    out: dict[str, dict] = {}
    for brand_id, entry in (stored or {}).items():
        active = (entry or {}).get("active")
        for v in (entry or {}).get("versions") or []:
            if v.get("version") == active:
                out[brand_id] = v.get("data") or {}
    return out
