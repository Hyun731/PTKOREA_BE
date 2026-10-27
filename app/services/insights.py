"""AI lead proposals (PRD 10, W01, W02, W04; DEVELOPMENT_PLAN T09).

The model only sees what the slide body shows: its displayed facts (as numbered refs),
its Finding's allowed expression and the page's visible text. It returns segments; a
number can only appear as a fact ref, so the server formats every number. Each proposal
is checked with the same rules as QC; up to 2 rewrites, then the rule lead stays.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs import register
from app.models import Job, LeadProposal, Project, new_id
from app.services.ledger import RunLedger
from app.services.inputs import load_inputs
from core.composition.build import build_deck
from core.composition.chrome import PartFactory
from core.composition.measure import line_count
from core.composition.tokens import region, type_spec
from core.quality.qc import FORBIDDEN_WORDS, OVERCLAIMS
from core.schemas.slidespec import Paragraph, Part, SlideSpec, TableBlock, TextBlock
from integrations.base import ProviderError

LEAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["segments"],
    "properties": {"segments": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["text", "fact_ref", "bold"],
        "properties": {"text": {"type": "string"}, "fact_ref": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                       "bold": {"type": "boolean"}}}}},
}

SYSTEM = """당신은 브랜드 마케팅 진단 보고서의 장표 리드 문장을 쓰는 편집자입니다.
규칙:
- 한국어, 최대 2줄(줄당 약 38자), 명사형으로 끝나는 문장.
- 숫자는 직접 쓰지 않습니다. 숫자가 필요하면 segments에 {"text": "", "fact_ref": 번호} 조각을 넣습니다. 숫자 조각은 최대 2개.
- 장표 본문에 실제로 보이는 사실과 제공된 '허용 표현'의 범위 안에서만 씁니다. 인과·의도 추측, 광고비·판매·실제 검색량 단정, 전략 제언은 쓰지 않습니다.
- 핵심 표현 1곳만 bold=true.
- 금지어: """ + ", ".join(FORBIDDEN_WORDS) + """
segments를 이어 붙이면 한 문장(또는 '—'로 이어진 두 구절)이 되도록 띄어쓰기를 포함해 나눕니다."""

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def _body_context(slide: SlideSpec) -> tuple[list[dict], str]:
    """Displayed facts (deduped, excluding the lead) and visible body text."""
    facts: list[dict] = []
    seen: set[str] = set()
    for b in slide.bindings:
        if b.block_id == "lead" or b.fact_id in seen:
            continue
        seen.add(b.fact_id)
        facts.append({"ref": len(facts) + 1, "fact_id": b.fact_id, "display": b.display, "entity": b.entity or "",
                      "metric": b.metric, "formatter": b.formatter})
    lines = []
    for blk in slide.blocks:
        if isinstance(blk, TextBlock) and blk.role not in ("lead", "badge", "footnote"):
            lines += [p.plain() for p in blk.paragraphs if p.parts]
        elif isinstance(blk, TableBlock):
            lines.append(" | ".join(c.label for c in blk.columns))
            for row in blk.rows[:8]:
                lines.append(" | ".join("".join(x.rendered() for p in c.paragraphs for x in p.parts) for c in row.cells))
    return facts[:24], "\n".join(lines)[:4000]


def _to_parts(segments: list[dict], facts: list[dict], pf: PartFactory) -> tuple[list[Part], list[str]]:
    errors: list[str] = []
    parts: list[Part] = []
    by_ref = {f["ref"]: f for f in facts}
    for s in segments:
        ref = s.get("fact_ref")
        if ref is not None:
            f = by_ref.get(ref)
            if not f:
                errors.append(f"없는 수치 참조 {ref}")
                continue
            parts.append(pf.fact(f["fact_id"], f["formatter"] or "int", bold=True))
        elif s.get("text"):
            parts.append(Part(type="text", text=s["text"], bold=bool(s.get("bold"))))
    return parts, errors


def check_lead(parts: list[Part]) -> list[str]:
    errors: list[str] = []
    text = "".join(p.rendered() for p in parts)
    if not text.strip():
        return ["빈 문장"]
    if sum(1 for p in parts if p.type == "fact") > 2:
        errors.append("숫자가 2개를 넘습니다")
    for p in parts:
        if p.type == "text" and re.search(r"\d", p.text or ""):
            errors.append(f"근거 없는 숫자: '{p.text.strip()}' — 숫자는 fact_ref로만 넣으세요")
    for w in FORBIDDEN_WORDS + OVERCLAIMS:
        if w in text:
            errors.append(f"쓸 수 없는 표현: '{w}'")
    ts = type_spec("lead")
    lines = line_count([(p.rendered(), "bold" if p.bold else ts.get("weight", "regular")) for p in parts],
                       region("lead").w, ts["size"])
    if lines > ts["max_lines"]:
        errors.append(f"{lines}줄입니다 — 2줄 이내로 줄이세요")
    return errors


@register("insight_proposals")
def run_insights(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    project = db.get(Project, job.project_id)
    inputs = load_inputs(db, project)
    result = build_deck(inputs)
    pf = PartFactory(result.metrics.registry)
    findings = {f.id: f for f in result.findings}
    only: Optional[list[str]] = job.params.get("slide_ids")
    targets = [s for s in result.deck.slides if s.page_role == "content" and any(isinstance(b, TextBlock) and b.role == "lead" for b in s.blocks)
               and (not only or s.slide_id in only)]
    ledger = RunLedger(db, project.id, job.id)
    # Older pending proposals for these slides are superseded by this run.
    db.execute(update(LeadProposal).where(LeadProposal.project_id == project.id, LeadProposal.status == "pending",
                                          LeadProposal.slide_id.in_([s.slide_id for s in targets])).values(status="superseded"))
    db.commit()
    made = failed = 0
    for i, slide in enumerate(targets):
        db.refresh(job)
        if job.state == "cancelled":
            break
        facts, body = _body_context(slide)
        lead_block = next(b for b in slide.blocks if isinstance(b, TextBlock) and b.role == "lead")
        allowed = [findings[fid].allowed_expression for fid in slide.finding_ids if fid in findings]
        user = (f"장표: {slide.title} ({slide.template_id})\n허용 표현: {', '.join(allowed) or '중립 설명(평가·단정 없이 보이는 내용 요약)'}\n"
                f"현재 리드(규칙 문장): {' '.join(p.plain() for p in lead_block.paragraphs)}\n"
                f"쓸 수 있는 수치(번호: 표시값 · 대상 · 지표):\n" + "\n".join(f"{f['ref']}: {f['display']} · {f['entity']} · {f['metric']}" for f in facts)
                + f"\n장표 본문:\n{body}")
        attempts, errors, parts = 0, [], []
        feedback = ""
        model = None
        while attempts < 3:
            attempts += 1
            try:
                res = ledger.call("anthropic", "lead", {"slide": slide.slide_id, "fp": result.deck.input_fingerprint,
                                                        "attempt": attempts, "fb": feedback}, 0.05,
                                  lambda: _structured()(SYSTEM, user + feedback, LEAD_SCHEMA, max_tokens=2000))
            except ProviderError as exc:
                errors = [f"{exc.code}: {exc.message}"]
                if exc.code == "BUDGET_EXCEEDED":
                    attempts = 3
                break
            model = res.usage.get("model")
            parts, conv_errors = _to_parts(res.data.get("segments") or [], facts, pf)
            errors = conv_errors + check_lead(parts)
            if not errors:
                break
            feedback = "\n\n이전 답의 문제: " + "; ".join(errors) + " — 고쳐서 다시 쓰세요."
        ok = not errors and parts
        db.add(LeadProposal(id=new_id("LP"), project_id=project.id, slide_id=slide.slide_id, slide_title=slide.title,
                            current=[json.loads(p.model_dump_json()) for p in lead_block.paragraphs],
                            parts=[json.loads(p.model_dump_json()) for p in parts] if ok else [],
                            status="pending" if ok else "failed", attempts=attempts, errors=errors, model=model,
                            fingerprint=result.deck.input_fingerprint, job_id=job.id))
        db.commit()
        made += bool(ok)
        failed += not ok
        progress(int((i + 1) / max(1, len(targets)) * 100))
    return {"proposed": made, "failed": failed, "spent_usd": round(ledger.spent(), 4)}


def accept_proposal(db: Session, proposal: LeadProposal, project: Project) -> None:
    project.lead_overrides = {**(project.lead_overrides or {}), proposal.slide_id: [{"parts": proposal.parts}]}
    proposal.status = "accepted"
