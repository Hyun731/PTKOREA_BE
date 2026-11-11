"""AI page writing (PRD 10, W01, W02, W04; IMPROVEMENT_PLAN P3-4/P3-5).

A headline is a claim (one line, one accent keyword) and up to two evidence lines ("- …"), each carrying one
or two numbers or a quoted phrase. The model only sees what the slide body shows: its displayed facts (as
numbered refs), its Finding's allowed expression and the page's visible text. It returns segments; a number
can only appear as a fact ref, so the server formats every number. Each answer is checked with the same rules
as QC; up to 2 rewrites, then the rule headline stays.

`write_slides` runs when a deck is built and keeps one headline plus three insight cards per page (SlideWriting,
reused while the page body is unchanged); `run_insights` makes headline proposals a person accepts one by one.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs import register
from app.models import Job, LeadProposal, Project, SlideWriting, new_id
from app.services.inputs import load_inputs
from app.services.ledger import RunLedger
from core.composition.build import body_fingerprint, build_deck, lead_of
from core.composition.chrome import EVIDENCE_BULLET, PartFactory
from core.composition.measure import line_count, paragraph_runs
from core.composition.tokens import region, type_spec
from core.quality.qc import FORBIDDEN_WORDS, OVERCLAIMS, self_brand_names, self_brands_in
from core.schemas.slidespec import Headline, Paragraph, Part, SlideSpec, TableBlock, TextBlock
from integrations.base import ProviderError

SEGMENTS = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["text", "fact_ref", "accent"],
    "properties": {"text": {"type": "string"}, "fact_ref": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                   "accent": {"type": "boolean"}}}}
LEAD_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["claim", "evidence"],
    "properties": {"claim": SEGMENTS, "evidence": {"type": "array", "items": SEGMENTS}},
}
PAGE_INSIGHT_ITEM_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["title", "body_segments"],
    "properties": {"title": SEGMENTS, "body_segments": SEGMENTS},
}
PAGE_INSIGHTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["insights"],
    "properties": {"insights": {"type": "array", "minItems": 3, "maxItems": 3, "items": PAGE_INSIGHT_ITEM_SCHEMA}},
}
MAX_EVIDENCE = 2
PAGE_INSIGHT_COUNT = 3
WRITERS = 6  # pages written at once when a deck is built

SYSTEM = """당신은 브랜드 마케팅 진단 보고서의 장표 헤드라인을 쓰는 편집자입니다.
헤드라인은 주장(claim) 한 줄과 그 근거(evidence) 두 줄입니다. 예)
  claim: 러기지 인지·신뢰는 확고한 1위, 35+에겐 '실패 없는 기준'
  evidence: - 러기지 고려 [수치]로 경쟁 세트 단독 1위, 보조인지 [수치]
            - '1황 브랜드의 신뢰감'·'매장 A/S'가 선택 이유
규칙:
- 한국어, 쉬운 말. claim은 30자 안팎 한 줄로, 이 장에서 읽히는 판단(강점·약점·이탈·격차·쏠림·공백)을 씁니다.
  claim의 핵심어 하나만 accent=true로 표시합니다(강조색). 명사형이나 '—'로 이어진 구절로 끝냅니다.
- evidence는 줄마다 한 줄(45자 안팎)이며, 숫자 1~2개 또는 본문에 보이는 원문 인용('…') 하나를 근거로 담습니다.
  evidence는 1~2줄이며, 근거 없는 claim은 쓰지 않습니다. 쓸 수 있는 수치가 있으면 수치를 먼저 쓰고, 수치가 없을 때 인용을 씁니다.
- 숫자는 직접 쓰지 않습니다. 숫자가 필요하면 segments에 {"text": "", "fact_ref": 번호} 조각을 넣습니다.
  쓸 수 있는 수치 목록에 있는 번호만 씁니다. 연도·기간·순위처럼 숫자가 든 말도 글자로 쓰지 않습니다.
  단, 장표 본문에 보이는 이름에 든 숫자(예: 29CM)는 이름 그대로 써도 됩니다.
- 장표 본문에 실제로 보이는 사실과 제공된 '허용 표현'의 범위 안에서만 씁니다. 판매·매출·광고비·실제 검색량에 대한
  인과 단정, 의도 추측, 전략 제언은 쓰지 않습니다.
- 자사 브랜드끼리 비교하지 않습니다. 한 헤드라인에는 자사 브랜드를 하나만 씁니다(경쟁사와의 비교는 괜찮습니다).
- 금지어: """ + ", ".join(FORBIDDEN_WORDS + OVERCLAIMS) + """
segments를 이어 붙이면 한 문장이 되도록 띄어쓰기를 포함해 나눕니다. evidence 줄 앞의 '-'는 쓰지 않습니다(서버가 붙임)."""

PAGE_INSIGHTS_SYSTEM = """당신은 브랜드 마케팅 진단 보고서의 장표 하단 인사이트 3개를 쓰는 편집자입니다.
각 인사이트는 제목(title)과 설명(body_segments) 한 줄씩이며, 세 카드는 서로 다른 관찰을 말합니다.
규칙:
- 한국어, 쉬운 말. 제목은 12자 안팎의 짧은 판단으로, 설명은 40자 안팎으로 씁니다.
- 설명마다 장표 본문에 보이는 수치 1~2개 또는 원문 인용('…') 하나를 반드시 근거로 넣습니다.
  수치를 쓰려면 segments에 {"text": "", "fact_ref": 번호} 조각을 넣습니다. 숫자를 직접 쓰지 않습니다.
- 설명은 다음 운영에서 무엇을 확인하거나 우선할지 알 수 있게 관찰의 의미를 덧붙이되, 판매·매출·광고비·실제 검색량의
  인과 단정, 의도 추측, 근거 없는 전략 제언은 쓰지 않습니다.
- 장표 본문에 실제로 보이는 사실과 제공된 '허용 표현'의 범위 안에서만 씁니다.
- 자사 브랜드끼리 비교하지 않습니다. 한 인사이트에는 자사 브랜드를 하나만 씁니다.
- 금지어: """ + ", ".join(FORBIDDEN_WORDS + OVERCLAIMS) + """
segments를 이어 붙이면 한 문장이 되도록 띄어쓰기를 포함해 나눕니다."""

# Indirection so tests can stub the model call.
STRUCTURED: list[Callable] = []


def _structured():
    if not STRUCTURED:
        from integrations.anthropic.client import structured
        STRUCTURED.append(structured)
    return STRUCTURED[0]


def ai_ready() -> bool:
    """Build-time writing runs only with a model (a key, or a test stub)."""
    from app.config import settings
    return bool(STRUCTURED) or settings.provider_configured("anthropic")


HEAD_BLOCKS = ("lead_claim", "lead_evidence")


def _body_context(slide: SlideSpec) -> tuple[list[dict], str]:
    """Displayed facts (deduped, excluding the headline and insights) and visible body text."""
    facts: list[dict] = []
    seen: set[str] = set()
    for b in slide.bindings:
        if b.block_id in HEAD_BLOCKS or b.block_id.startswith("insight") or b.fact_id in seen:
            continue
        seen.add(b.fact_id)
        facts.append({"ref": len(facts) + 1, "fact_id": b.fact_id, "display": b.display, "entity": b.entity or "",
                      "metric": b.metric, "formatter": b.formatter})
    lines = []
    for blk in slide.blocks:
        if blk.block_id.startswith("insight"):
            continue
        if isinstance(blk, TextBlock) and blk.role not in ("lead", "lead_evidence", "insight", "badge", "footnote",
                                                             "chip", "page_no", "title"):
            lines += [p.plain() for p in blk.paragraphs if p.parts]
        elif isinstance(blk, TableBlock):
            lines.append(" | ".join(c.label for c in blk.columns))
            for row in blk.rows[:8]:
                lines.append(" | ".join("".join(x.rendered() for p in c.paragraphs for x in p.parts) for c in row.cells))
    return facts[:24], "\n".join(lines)[:4000]


def digit_names(slide: SlideSpec, extra: Iterable[str] = ()) -> list[str]:
    """Fixed names with digits shown on the page ("29CM", "W컨셉 2.0"): the model may write them as text."""
    names = {p.text for b in slide.blocks if isinstance(b, TextBlock) for para in b.paragraphs for p in para.parts
             if p.type == "name" and p.text}
    names |= {p.text for b in slide.blocks if isinstance(b, TableBlock) for r in b.rows for c in r.cells
              for para in c.paragraphs for p in para.parts if p.type == "name" and p.text}
    names |= set(extra)
    found: set[str] = set()
    for n in names:  # long names (card labels) also yield their digit words: "브랜든 × 29CM 단독" -> "29CM"
        found |= {w.strip("'\"‘’“”()[]·,") for w in n.split() if re.search(r"\d", w)}
    return sorted((n for n in found if n and len(n) <= 20), key=len, reverse=True)


def _name_parts(text: str, names: list[str]) -> list[Part]:
    """Text with digit-bearing names typed as name parts (QC reads those as names, not numbers)."""
    for name in names:
        i = text.find(name)
        if i >= 0:
            before, after = text[:i], text[i + len(name):]
            return [*(_name_parts(before, names) if before else []), Part(type="name", text=name),
                    *(_name_parts(after, names) if after else [])]
    return [Part(type="text", text=text)]


def _to_parts(segments: list[dict], facts: list[dict], pf: PartFactory, *, claim: bool = True,
              names: Iterable[str] = ()) -> tuple[list[Part], list[str]]:
    names = list(names)
    errors: list[str] = []
    parts: list[Part] = []
    by_ref = {f["ref"]: f for f in facts}
    accented = False
    for s in segments:
        ref = s.get("fact_ref")
        if ref is not None:
            f = by_ref.get(ref)
            if not f:
                errors.append(f"없는 수치 참조 {ref}")
                continue
            part = pf.fact(f["fact_id"], f["formatter"] or "int", bold=claim)
            parts.append(part if claim else part.model_copy(update={"weight": "semibold", "color": "navy"}))
        elif s.get("text"):
            text = s["text"]
            if not claim and not parts:
                text = text.lstrip(" -–·•")  # the server draws the "- " marker
            is_accent = claim and bool(s.get("accent")) and not accented and text.strip()
            accented = accented or bool(is_accent)
            parts += [p.model_copy(update={"color": "accent"}) if is_accent else p for p in _name_parts(text, names)]
    return parts, errors


def headline_from(data: dict, facts: list[dict], pf: PartFactory, names: Iterable[str] = ()) -> tuple[Headline, list[str]]:
    """Model answer -> Headline (claim + evidence paragraphs) and conversion errors."""
    names = list(names)
    claim, errors = _to_parts(data.get("claim") or data.get("segments") or [], facts, pf, names=names)
    evidence: list[Paragraph] = []
    for seg in (data.get("evidence") or [])[:MAX_EVIDENCE]:
        parts, errs = _to_parts(seg or [], facts, pf, claim=False, names=names)
        errors += errs
        if parts:
            evidence.append(Paragraph(parts=parts))
    return Headline(claim=[Paragraph(parts=claim)] if claim else [], evidence=evidence), errors


def _plain_errors(parts: list[Part]) -> list[str]:
    errors: list[str] = []
    text = "".join(p.rendered() for p in parts)
    for p in parts:
        if p.type == "text" and re.search(r"\d", p.text or ""):
            errors.append(f"근거 없는 숫자: '{p.text.strip()}' — 숫자는 fact_ref로만 넣으세요")
    for w in FORBIDDEN_WORDS + OVERCLAIMS:
        if w in text:
            errors.append(f"쓸 수 없는 표현: '{w}'")
    return errors


def check_lead(parts: list[Part], spec: str = "lead") -> list[str]:
    """Rules for the claim (or a claim-only headline): text, at most 2 numbers, fits the lines of `spec`."""
    text = "".join(p.rendered() for p in parts)
    if not text.strip():
        return ["빈 문장"]
    errors = _plain_errors(parts)
    if sum(1 for p in parts if p.type == "fact") > 2:
        errors.append("숫자가 2개를 넘습니다")
    ts = type_spec(spec)
    lines = line_count([(p.rendered(), "bold" if p.bold else ts.get("weight", "regular")) for p in parts],
                       region("lead").w, ts["size"])
    if lines > ts["max_lines"]:
        errors.append(f"{lines}줄입니다 — {ts['max_lines']}줄 이내로 줄이세요")
    return errors


QUOTED = re.compile(r"['‘“\"「『][^'’”\"」』]{2,}['’”\"」』]")


def check_headline(head: Headline, self_brands: Iterable[str] = ()) -> list[str]:
    """QC rules for a claim + evidence headline (P3-4)."""
    claim = [p for para in head.claim for p in para.parts]
    if not head.evidence:
        return check_lead(claim) + ["근거 줄이 없습니다 — 수치나 원문 인용이 든 근거 1~2줄을 붙이세요"]
    errors = [f"주장: {e}" for e in check_lead(claim, "lead_claim")]
    ts = type_spec("lead_evidence")
    for i, para in enumerate(head.evidence[:MAX_EVIDENCE], start=1):
        text = para.plain().strip()
        if not text:
            errors.append(f"근거 {i}: 빈 줄")
            continue
        errors += [f"근거 {i}: {e}" for e in _plain_errors(para.parts)]
        n = sum(1 for p in para.parts if p.type == "fact")
        if n > 2:
            errors.append(f"근거 {i}: 숫자가 2개를 넘습니다")
        if n == 0 and not QUOTED.search(text):
            errors.append(f"근거 {i}: 수치(fact_ref)나 원문 인용('…')이 없습니다")
        runs = paragraph_runs(para.model_copy(update={"bullet": EVIDENCE_BULLET}), ts.get("weight"))
        if line_count(runs, region("lead").w, ts["size"]) > 1:
            errors.append(f"근거 {i}: 한 줄을 넘습니다 — 줄이세요")
    names = self_brands_in(" ".join(p.plain() for p in [*head.claim, *head.evidence]), self_brands)
    if len(names) > 1:
        errors.append(f"자사 브랜드끼리 비교: {', '.join(sorted(names))} — 자사 브랜드는 하나만 쓰세요")
    return errors


def _user_prompt(slide: SlideSpec, facts: list[dict], body: str, allowed: list[str], self_brands: list[str]) -> str:
    lead = lead_of(slide)
    current = " ".join(p.plain() for p in lead.paragraphs) if lead else ""
    return (f"장표: {slide.title} ({slide.template_id})\n허용 표현: {', '.join(allowed) or '중립 설명(평가·단정 없이 보이는 내용 요약)'}\n"
            f"자사 브랜드: {', '.join(self_brands)}\n"
            f"현재 헤드라인(규칙 문장): {current}\n"
            f"쓸 수 있는 수치(번호: 표시값 · 대상 · 지표):\n"
            + "\n".join(f"{f['ref']}: {f['display']} · {f['entity']} · {f['metric']}" for f in facts)
            + f"\n장표 본문:\n{body}")


def _page_insights_prompt(slide: SlideSpec, facts: list[dict], body: str, allowed: list[str], self_brands: list[str]) -> str:
    return (f"장표: {slide.title} ({slide.template_id})\n허용 표현: {', '.join(allowed) or '중립 설명(평가·단정 없이 보이는 내용 요약)'}\n"
            f"자사 브랜드: {', '.join(self_brands)}\n"
            f"쓸 수 있는 수치(번호: 표시값 · 대상 · 지표):\n"
            + "\n".join(f"{f['ref']}: {f['display']} · {f['entity']} · {f['metric']}" for f in facts)
            + f"\n장표 본문:\n{body}")


def _insight_column_width() -> float:
    reg = region("insights")
    return (reg.w + 10) / 3 - 10 - 21


def page_insights_from(data: dict, facts: list[dict], pf: PartFactory,
                       names: Iterable[str] = ()) -> tuple[list[dict], list[str]]:
    """Model answer -> P3-5 insight cards and conversion errors."""
    names = list(names)
    cards: list[dict] = []
    errors: list[str] = []
    for index, item in enumerate(data.get("insights") or [], start=1):
        title, title_errors = _to_parts(item.get("title") or [], facts, pf, claim=False, names=names)
        body, body_errors = _to_parts(item.get("body_segments") or [], facts, pf, claim=False, names=names)
        errors += [f"인사이트 {index}: {error}" for error in [*title_errors, *body_errors]]
        cards.append({"title": Paragraph(parts=title), "body_segments": Paragraph(parts=body)})
    return cards, errors


def check_page_insights(cards: list[dict], self_brands: Iterable[str] = ()) -> list[str]:
    """P3-5 cards share the headline safeguards and each carry displayed evidence."""
    if len(cards) != PAGE_INSIGHT_COUNT:
        return [f"인사이트는 {PAGE_INSIGHT_COUNT}개여야 합니다"]
    errors: list[str] = []
    title_spec = type_spec("insight_title")
    body_spec = type_spec("insight_body")
    width = _insight_column_width()
    all_text: list[str] = []
    for index, card in enumerate(cards, start=1):
        title = card["title"].parts
        body = card["body_segments"].parts
        if not "".join(part.rendered() for part in title).strip():
            errors.append(f"인사이트 {index}: 빈 제목")
        if not "".join(part.rendered() for part in body).strip():
            errors.append(f"인사이트 {index}: 빈 설명")
        errors += [f"인사이트 {index} 제목: {error}" for error in _plain_errors(title)]
        errors += [f"인사이트 {index} 설명: {error}" for error in _plain_errors(body)]
        if line_count(paragraph_runs(Paragraph(parts=title), title_spec.get("weight")), width, title_spec["size"]) > 1:
            errors.append(f"인사이트 {index}: 제목이 한 줄을 넘습니다 — 줄이세요")
        if line_count(paragraph_runs(Paragraph(parts=body), body_spec.get("weight")), width, body_spec["size"]) > body_spec["max_lines"]:
            errors.append(f"인사이트 {index}: 설명이 {body_spec['max_lines']}줄을 넘습니다 — 줄이세요")
        facts = sum(1 for part in body if part.type == "fact")
        if facts > 2:
            errors.append(f"인사이트 {index}: 숫자가 2개를 넘습니다")
        text = "".join(part.rendered() for part in body)
        if facts == 0 and not QUOTED.search(text):
            errors.append(f"인사이트 {index}: 수치(fact_ref)나 원문 인용('…')이 없습니다")
        all_text.append("".join(part.rendered() for part in [*title, *body]))
    names = self_brands_in(" ".join(all_text), self_brands)
    if len(names) > 1:
        errors.append(f"자사 브랜드끼리 비교: {', '.join(sorted(names))} — 자사 브랜드는 하나만 쓰세요")
    return errors


def propose(slide: SlideSpec, allowed: list[str], pf: PartFactory, ledger: RunLedger, fp: str,
            self_brands: list[str], endpoint: str = "lead") -> dict:
    """One headline for one page: up to 3 answers, each checked like QC. Returns
    {"head": Headline | None, "errors", "attempts", "model"}; raises ProviderError when the model can't be reached."""
    facts, body = _body_context(slide)
    names = digit_names(slide, self_brands)
    user = _user_prompt(slide, facts, body, allowed, self_brands)
    attempts, errors, head, model, feedback = 0, [], None, None, ""
    while attempts < 3:
        attempts += 1
        res = ledger.call("anthropic", endpoint, {"slide": slide.slide_id, "fp": fp, "attempt": attempts, "fb": feedback,
                                                  "v": 2}, 0.05,
                          lambda: _structured()(SYSTEM, user + feedback, LEAD_SCHEMA, max_tokens=2000))
        model = res.usage.get("model")
        head, conv = headline_from(res.data, facts, pf, names)
        errors = conv + check_headline(head, self_brands)
        if not errors:
            break
        feedback = "\n\n이전 답의 문제: " + "; ".join(errors) + " — 고쳐서 다시 쓰세요."
    return {"head": None if errors else head, "errors": errors, "attempts": attempts, "model": model}


def page_insights(slide: SlideSpec, allowed: list[str], pf: PartFactory, ledger: RunLedger, fp: str,
                  self_brands: list[str], endpoint: str = "page_insights") -> dict:
    """Three evidence-backed cards for one content page, retried under the same prose constraints as leads."""
    facts, body = _body_context(slide)
    names = digit_names(slide, self_brands)
    user = _page_insights_prompt(slide, facts, body, allowed, self_brands)
    attempts, errors, cards, model, feedback = 0, [], [], None, ""
    while attempts < 3:
        attempts += 1
        res = ledger.call("anthropic", endpoint, {"slide": slide.slide_id, "fp": fp, "attempt": attempts, "fb": feedback,
                                                    "v": 1}, 0.05,
                          lambda: _structured()(PAGE_INSIGHTS_SYSTEM, user + feedback, PAGE_INSIGHTS_SCHEMA, max_tokens=2400))
        model = res.usage.get("model")
        cards, conversion_errors = page_insights_from(res.data, facts, pf, names)
        errors = conversion_errors + check_page_insights(cards, self_brands)
        if not errors:
            break
        feedback = "\n\n이전 답의 문제: " + "; ".join(errors) + " — 고쳐서 다시 쓰세요."
    return {"insights": cards if not errors else [], "errors": errors, "attempts": attempts, "model": model}


def _dump(head: Headline) -> dict:
    return {"claim": [json.loads(p.model_dump_json()) for p in head.claim],
            "evidence": [json.loads(p.model_dump_json()) for p in head.evidence]}


def dump_page_insights(cards: list[dict]) -> dict:
    return {"insights": [{"title": json.loads(card["title"].model_dump_json()),
                          "body_segments": json.loads(card["body_segments"].model_dump_json())} for card in cards]}


def _allowed(slide: SlideSpec, findings: dict) -> list[str]:
    return [findings[fid].allowed_expression for fid in slide.finding_ids if fid in findings]


def write_headlines(db: Session, project: Project, result, ledger: RunLedger,
                    progress: Optional[Callable[[int], None]] = None) -> dict:
    """Build-time headlines (P3-4): every content page with a headline and no person-written one gets an AI
    headline, written once per page body and kept in SlideWriting. Pages whose rewrite still breaks the rules
    keep the rule headline (stored as failed, so the same body is not retried every build)."""
    overrides = project.lead_overrides or {}
    stored = {w.slide_id: w for w in db.scalars(select(SlideWriting).where(SlideWriting.project_id == project.id,
                                                                          SlideWriting.kind == "lead"))}
    todo: list[tuple[SlideSpec, str]] = []
    for s in result.deck.slides:
        if s.page_role != "content" or lead_of(s) is None or s.slide_id in overrides:
            continue
        fp = body_fingerprint(s)
        if s.slide_id in stored and stored[s.slide_id].body_fp == fp:
            continue
        todo.append((s, fp))
    if not todo:
        return {"written": 0, "failed": 0, "kept": len(stored)}
    pf = PartFactory(result.metrics.registry)
    findings = {f.id: f for f in result.findings}
    brands = sorted(self_brand_names(project.config))
    db.commit()  # the ledger writes in its own sessions (SQLite: one writer)
    _structured()  # resolve the model function once, before the workers share it

    def one(item):
        slide, fp = item
        try:
            return slide, fp, propose(slide, _allowed(slide, findings), pf, ledger, fp, brands), None
        except ProviderError as exc:
            return slide, fp, None, exc

    written = failed = done = 0
    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        for slide, fp, out, exc in pool.map(one, todo):
            done += 1
            if progress:
                progress(int(done / len(todo) * 100))
            if exc is not None:  # the model could not be reached: nothing is stored, the next build tries again
                failed += 1
                continue
            row = stored.get(slide.slide_id) or SlideWriting(id=new_id("SW"), project_id=project.id,
                                                              slide_id=slide.slide_id, kind="lead")
            row.body_fp, row.attempts, row.model, row.errors = fp, out["attempts"], out["model"], out["errors"]
            row.status = "ok" if out["head"] else "failed"
            row.data = _dump(out["head"]) if out["head"] else {}
            db.add(row)
            written += bool(out["head"])
            failed += not out["head"]
    db.commit()
    return {"written": written, "failed": failed, "kept": len(stored)}


def write_page_insights(db: Session, project: Project, result, ledger: RunLedger,
                        progress: Optional[Callable[[int], None]] = None) -> dict:
    """Build-time P3-5 cards for every content page; a person's saved cards always win."""
    overrides = project.insight_overrides or {}
    stored = {w.slide_id: w for w in db.scalars(select(SlideWriting).where(SlideWriting.project_id == project.id,
                                                                          SlideWriting.kind == "insights"))}
    todo: list[tuple[SlideSpec, str]] = []
    for slide in result.deck.slides:
        if slide.page_role != "content" or lead_of(slide) is None or slide.slide_id in overrides:
            continue
        fp = body_fingerprint(slide)
        if slide.slide_id in stored and stored[slide.slide_id].body_fp == fp:
            continue
        todo.append((slide, fp))
    if not todo:
        return {"written": 0, "failed": 0, "kept": len(stored)}
    pf = PartFactory(result.metrics.registry)
    findings = {f.id: f for f in result.findings}
    brands = sorted(self_brand_names(project.config))
    db.commit()  # the ledger writes in its own sessions (SQLite: one writer)
    _structured()  # resolve the model function once, before the workers share it

    def one(item):
        slide, fp = item
        try:
            return slide, fp, page_insights(slide, _allowed(slide, findings), pf, ledger, fp, brands), None
        except ProviderError as exc:
            return slide, fp, None, exc

    written = failed = done = 0
    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        for slide, fp, out, exc in pool.map(one, todo):
            done += 1
            if progress:
                progress(int(done / len(todo) * 100))
            if exc is not None:
                failed += 1
                continue
            row = stored.get(slide.slide_id) or SlideWriting(id=new_id("SW"), project_id=project.id,
                                                              slide_id=slide.slide_id, kind="insights")
            row.body_fp, row.attempts, row.model, row.errors = fp, out["attempts"], out["model"], out["errors"]
            row.status = "ok" if out["insights"] else "failed"
            row.data = dump_page_insights(out["insights"]) if out["insights"] else {}
            db.add(row)
            written += bool(out["insights"])
            failed += not out["insights"]
    db.commit()
    return {"written": written, "failed": failed, "kept": len(stored)}


def write_slides(db: Session, project: Project, job_id: Optional[str] = None,
                 progress: Optional[Callable[[int], None]] = None) -> dict:
    """Everything the AI writes into a deck at build time. Never fails the build: errors are reported."""
    if not ai_ready():
        return {"skipped": "AI 키 없음"}
    result = build_deck(load_inputs(db, project))
    ledger = RunLedger(db, project.id, job_id)
    out = {"lead": write_headlines(db, project, result, ledger, progress),
           "insights": write_page_insights(db, project, result, ledger, progress)}
    return out


@register("insight_proposals")
def run_insights(db: Session, job: Job, progress: Callable[[int], None]) -> dict:
    project = db.get(Project, job.project_id)
    inputs = load_inputs(db, project)
    result = build_deck(inputs)
    pf = PartFactory(result.metrics.registry)
    findings = {f.id: f for f in result.findings}
    only: Optional[list[str]] = job.params.get("slide_ids")
    targets = [s for s in result.deck.slides if s.page_role == "content" and lead_of(s) is not None
               and (not only or s.slide_id in only)]
    ledger = RunLedger(db, project.id, job.id)
    brands = sorted(self_brand_names(project.config))
    # Older pending proposals for these slides are superseded by this run.
    db.execute(update(LeadProposal).where(LeadProposal.project_id == project.id, LeadProposal.status == "pending",
                                          LeadProposal.slide_id.in_([s.slide_id for s in targets])).values(status="superseded"))
    db.commit()
    made = failed = 0
    for i, slide in enumerate(targets):
        db.refresh(job)
        if job.state == "cancelled":
            break
        try:
            out = propose(slide, _allowed(slide, findings), pf, ledger, result.deck.input_fingerprint, brands)
        except ProviderError as exc:
            out = {"head": None, "errors": [f"{exc.code}: {exc.message}"], "attempts": 1, "model": None}
        current = [json.loads(p.model_dump_json()) for b in slide.blocks if isinstance(b, TextBlock)
                   and b.role in ("lead", "lead_evidence") for p in b.paragraphs]
        ok = out["head"] is not None
        db.add(LeadProposal(id=new_id("LP"), project_id=project.id, slide_id=slide.slide_id, slide_title=slide.title,
                            current=current, parts=_dump(out["head"]) if ok else [],
                            status="pending" if ok else "failed", attempts=out["attempts"], errors=out["errors"],
                            model=out["model"], fingerprint=result.deck.input_fingerprint, job_id=job.id))
        db.commit()
        made += ok
        failed += not ok
        progress(int((i + 1) / max(1, len(targets)) * 100))
    return {"proposed": made, "failed": failed, "spent_usd": round(ledger.spent(), 4)}


def accept_proposal(db: Session, proposal: LeadProposal, project: Project) -> None:
    """A proposal holds {"claim", "evidence"} paragraphs (P3-4); older ones a list of claim parts."""
    parts = proposal.parts
    head = parts if isinstance(parts, dict) else {"claim": [{"parts": parts}], "evidence": []}
    project.lead_overrides = {**(project.lead_overrides or {}), proposal.slide_id: head}
    proposal.status = "accepted"
