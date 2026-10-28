"""P4 사례 카드 해설 (06_AI_프롬프트_템플릿.md §P4; competitor/benchmark case cards only).

Mirrors app/services/insights.py's pattern (P3): a background job proposes text for a
person to review, nothing is written to a material until accepted. The output is plain
qualitative text (무엇을 했고 왜 통했나 / 자사 시사점) — no numbers, since the card already
shows its key figure separately (core/composition/cases.py case_detail_pages 'figure' tile);
asking the model to restate a number here would just reopen the unbound-number problem P3
already solves by binding leads to fact refs.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs import register
from app.models import CaseCommentary, Job, Material, Project, new_id
from app.services.inputs import core_project, load_inputs
from app.services.ledger import RunLedger
from core.composition.cases import eligible_case
from core.composition.measure import line_count, paragraph_runs
from core.quality.qc import FORBIDDEN_WORDS, OVERCLAIMS, self_brand_names
from core.schemas.slidespec import Paragraph, Part
from integrations.base import ProviderError

# detail becomes the case card's lead (core/composition/cases.py case_detail_pages: a custom
# Region(w=1184, h=50) at size 19/line 25, weight resolved from the generic "lead" type_spec =
# bold, not the generic lead spec's own region); implication becomes the standard takeaway block
# (region("takeaway"), type_spec("takeaway") size 11/line 16, weight semibold). Measuring against
# the exact block + resolved weight each one renders with — the same way core/quality/qc.py's
# TEXT_OVERFLOW check does via paragraph_runs()/line_count() — is required: a plain character
# count under-predicts width because both blocks render bold/semibold, which is wider per char.
_LEAD = {"w": 1184.0, "h": 50.0, "size": 19.0, "line": 25.0, "weight": "bold"}
_TAKEAWAY = {"w": 1184.0, "h": 38.0, "size": 11.0, "line": 16.0, "weight": "semibold"}
DETAIL_MAX, IMPLICATION_MAX = 70, 55  # chars; a coarse backstop, the real check is _overflows()


def _overflows(text: str, spec: dict) -> bool:
    para = Paragraph(parts=[Part(type="text", text=text)])
    runs = paragraph_runs(para, spec["weight"], False)
    lines = line_count(runs, spec["w"], spec["size"])
    needed = lines * spec["line"] * 96 / 72
    return needed > spec["h"] + 4

CASE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["detail", "implication"],
    "properties": {"detail": {"type": "string"}, "implication": {"type": "string"}},
}

SYSTEM = """너는 브랜드 디지털 마케팅 리서치 애널리스트다. 한국어 명사형 압축 문체로 쓴다.
절대 규칙:
1) 입력으로 받은 사실에 없는 수치·사실을 만들지 않는다.
2) 자사 브랜드끼리 비교하지 않는다.
3) '데이터 부재·확인 필요·재측정 필요·정성 분석' 같은 표현을 쓰지 않는다.
4) 숫자를 절대 쓰지 않는다 — 핵심 수치는 카드에 이미 따로 표시된다. 숫자가 필요한 설명이면 "큰 폭", "짧은 기간" 처럼 수치 없는 표현으로 바꾼다.
5) 출처·URL·브랜드명 코드(F-, EV- 등)는 쓰지 않는다.

과제: 아래 경쟁사 사례 사실을 보고 두 줄을 써라.
- detail: 무엇을 했고 왜 통했나, 1줄(60자 내외)
- implication: {자사 브랜드}에 적용할 시사점, 1줄(40자 내외)
금지어: """ + ", ".join(FORBIDDEN_WORDS + OVERCLAIMS)

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


DIGIT = re.compile(r"\d")


def check_commentary(detail: str, implication: str) -> list[str]:
    errors = []
    if not detail.strip() or not implication.strip():
        errors.append("빈 문장")
    if DIGIT.search(detail) or DIGIT.search(implication):
        errors.append("숫자가 포함됨 — 수치 없는 표현으로 바꾸세요")
    if len(detail) > DETAIL_MAX or _overflows(detail, _LEAD):
        errors.append(f"detail이 카드 영역을 넘칩니다({len(detail)}자) — 더 짧게 줄이세요")
    if len(implication) > IMPLICATION_MAX or _overflows(implication, _TAKEAWAY):
        errors.append(f"implication이 카드 영역을 넘칩니다({len(implication)}자) — 더 짧게 줄이세요")
    for w in FORBIDDEN_WORDS + OVERCLAIMS:
        if w in detail or w in implication:
            errors.append(f"쓸 수 없는 표현: '{w}'")
    return errors


def _case_facts(m, pf) -> str:
    lines = [f"브랜드: {m.entity}"]
    if m.event_name:
        lines.append(f"활동: {m.event_name}")
    if m.activity_date:
        lines.append(f"시기: {m.activity_date}")
    quotes = [c.quote for c in m.claims if c.review_status == "accepted" and c.quote]
    for q in dict.fromkeys(quotes):
        lines.append(f"사실: {q}")
    for fid in m.metric_fact_ids[:2]:
        obj = pf.registry.get(fid)
        if obj is not None and getattr(obj, "label", None):
            lines.append(f"수치 맥락: {obj.label} 관련 성과 있음(구체값은 카드에 별도 표시)")
    return "\n".join(lines)


@register("case_commentary")
def run_case_commentary(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    from core.composition.chrome import PartFactory
    from core.metrics.engine import compute

    project = db.get(Project, job.project_id)
    core = core_project(project)
    self_names = self_brand_names(project.config)
    inputs = load_inputs(db, project)
    metrics = compute(inputs.project, inputs.facts, inputs.posts)
    pf = PartFactory(metrics.registry)

    only: Optional[list[str]] = job.params.get("material_ids")
    targets = [m for m in inputs.materials if m.section_id == "campaign" and eligible_case(m) is None
              and m.entity not in self_names and (not only or m.id in only)]
    ledger = RunLedger(db, project.id, job.id)
    db.execute(update(CaseCommentary).where(CaseCommentary.project_id == project.id, CaseCommentary.status == "pending",
                                            CaseCommentary.material_id.in_([m.id for m in targets])).values(status="superseded"))
    db.commit()

    made = failed = 0
    for i, m in enumerate(targets):
        db.refresh(job)
        if job.state == "cancelled":
            break
        brand_name = next((b.name for b in core.brands if m.brand_id == b.id), core.brands[0].name)
        user = f"자사 브랜드: {brand_name}\n\n{_case_facts(m, pf)}"
        attempts, errors, detail, implication, model = 0, [], "", "", None
        feedback = ""
        while attempts < 3:
            attempts += 1
            try:
                res = ledger.call("anthropic", "case_commentary", {"material": m.id, "attempt": attempts, "fb": feedback},
                                  0.03, lambda: _structured()(SYSTEM, user + feedback, CASE_SCHEMA, max_tokens=500))
            except ProviderError as exc:
                errors = [f"{exc.code}: {exc.message}"]
                if exc.code == "BUDGET_EXCEEDED":
                    attempts = 3
                break
            model = res.usage.get("model")
            detail, implication = (res.data.get("detail") or "").strip(), (res.data.get("implication") or "").strip()
            errors = check_commentary(detail, implication)
            if not errors:
                break
            feedback = "\n\n이전 답의 문제: " + "; ".join(errors) + " — 고쳐서 다시 쓰세요."
        ok = not errors and detail and implication
        db.add(CaseCommentary(id=new_id("CC"), project_id=project.id, material_id=m.id, detail=detail if ok else None,
                              implication=implication if ok else None, status="pending" if ok else "failed",
                              attempts=attempts, errors=errors, model=model, job_id=job.id))
        db.commit()
        made += bool(ok)
        failed += not ok
        progress(int((i + 1) / max(1, len(targets)) * 100))
    return {"proposed": made, "failed": failed, "spent_usd": round(ledger.spent(), 4)}


def accept_case_commentary(db: Session, c: CaseCommentary) -> None:
    m = db.get(Material, c.material_id)
    m.ai_detail, m.ai_implication = c.detail, c.implication
    m.version += 1
    c.status = "accepted"
