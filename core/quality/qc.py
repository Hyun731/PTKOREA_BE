"""QC (PRD 12). Element-level binding checks, not string-set matching.

block issues cannot be downgraded; warn issues are reviewable. Passing QC means the rule
checks found nothing, not that every sentence is factually proven (DEVELOPMENT_PLAN 8).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

from core.composition.formatters import format_value
from core.composition.measure import line_count, paragraph_runs
from core.composition.tokens import tokens
from core.metrics.registry import FactRegistry
from core.schemas.facts import Fact
from core.schemas.materials import AssetRef
from core.schemas.slidespec import (
    BarChartBlock, DeckSpec, ImageBlock, LineChartBlock, Paragraph, SlideSpec, TableBlock, TextBlock,
)

Severity = Literal["block", "warn"]
FRAME_ROLES = {"cover", "index", "divider", "end"}

FORBIDDEN_WORDS = ["검토 필요", "재측정 필요", "공개 자료 없음", "측정 불가", "부스트", "Earned 강도", "N/A", "조사 필요", "TODO", "TBD",
                   "데이터 부재", "확인 필요", "정성 분석"]
INTERNAL_ID = re.compile(r"\b(?:F|DF|FN|SRC|EV|AS|CL)-[0-9A-Za-z]{4,}")
# Assertions the data cannot support (ad heuristics / relative search indexes as facts).
OVERCLAIMS = ["광고 집행 게시물", "유료 광고 게시물", "광고비 투입", "광고비를", "검색량이 증가", "검색량 증가", "판매 증가",
              "매출 증가", "구매 전환 저하", "관심이 이동", "관심 이동", "시장 점유율"]
DIGIT = re.compile(r"\d")


@dataclass
class Issue:
    code: str
    severity: Severity
    message: str
    action: str
    slide_id: Optional[str] = None
    block_id: Optional[str] = None


@dataclass
class QCReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def blocks(self) -> int:
        return sum(1 for i in self.issues if i.severity == "block")

    @property
    def warns(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warn")

    def to_dict(self) -> dict:
        return {"blocks": self.blocks, "warns": self.warns, "issues": [asdict(i) for i in self.issues]}


AssetLookup = Callable[[str], Optional[AssetRef]]


def self_brand_names(project_config: dict) -> frozenset[str]:
    """Names of the client's own brands in a project (never compared against each other)."""
    return frozenset(b["name"] for b in project_config.get("brands", []))


def run_qc(deck: DeckSpec, registry: FactRegistry, assets: AssetLookup,
           self_brands: Optional[frozenset[str]] = None) -> QCReport:
    report = QCReport()
    add = report.issues.append
    for slot in deck.plan:
        if slot.readiness == "needs_input":
            # Everything is in the plan by default; a part with no data simply stays out of this deck.
            add(Issue("SLOT_NEEDS_INPUT", "warn", f"{slot.label}: 자료가 없어 이번 덱에서 빠짐 ({slot.reason})",
                      "자료를 채택하면 다음 생성 때 들어갑니다", block_id=slot.slot_id))
        elif slot.readiness == "omitted":
            add(Issue("SLOT_OMITTED", "warn", f"{slot.label} 생략: {slot.reason}", "생략 목록 확인", block_id=slot.slot_id))
    if not any(s.is_data for s in deck.slides):
        add(Issue("NO_DATA_SLIDES", "block", "본문 데이터 장표가 0개입니다", "최소 자료를 채택한 뒤 다시 생성"))
    for slide in deck.slides:
        _check_slide(slide, registry, assets, add, self_brands)
    return report


def _paragraph_runs(p: Paragraph, block_weight=None, block_bold: bool = False):
    return paragraph_runs(p, block_weight, block_bold)


def _text_parts(slide: SlideSpec):
    """(block_id, part) for all customer-visible text parts."""
    for b in slide.blocks:
        if isinstance(b, TextBlock):
            for p in b.paragraphs:
                for part in p.parts:
                    yield b.block_id, b, part
        elif isinstance(b, TableBlock):
            for r_i, row in enumerate(b.rows):
                for c_i, cell in enumerate(row.cells):
                    for p in cell.paragraphs:
                        for part in p.parts:
                            yield f"{b.block_id}[{r_i},{c_i}]", b, part


def _check_slide(slide: SlideSpec, registry: FactRegistry, assets: AssetLookup, add,
                  self_brands: Optional[frozenset[str]] = None):
    sid = slide.slide_id
    canvas = tokens()["canvas"]
    frame = slide.page_role in FRAME_ROLES

    # 1. bindings: every fact part resolves, is usable, and shows its formatted value
    for block_id, _, part in _text_parts(slide):
        if part.type != "fact":
            continue
        _check_fact(sid, block_id, part.fact_id, part.formatter, part.display, registry, add)
    for b in slide.blocks:
        if isinstance(b, BarChartBlock):
            for it in b.items:
                _check_fact(sid, b.block_id, it.fact_id, "share", it.display, registry, add)
        elif isinstance(b, LineChartBlock):
            for s in b.series:
                for pt in s.points:
                    if pt.fact_id:
                        _check_fact(sid, b.block_id, pt.fact_id, None, None, registry, add)

    # 2. digits in plain text must be typed (fact/date/meta/name/link)
    if not frame:
        for block_id, _, part in _text_parts(slide):
            if part.type == "text" and part.text and DIGIT.search(part.text):
                add(Issue("UNBOUND_NUMBER", "block", f"근거 연결 없는 숫자: '{part.text.strip()}'",
                          "숫자를 Fact로 연결하거나 문장에서 제거", sid, block_id))

    # 3. customer-facing wording
    for block_id, _, part in _text_parts(slide):
        text = part.rendered()
        for word in FORBIDDEN_WORDS:
            if word in text:
                add(Issue("FORBIDDEN_WORD", "block", f"고객용 금지어 '{word}'", "문구 수정", sid, block_id))
        if INTERNAL_ID.search(text):
            add(Issue("INTERNAL_ID", "block", "내부 ID 노출", "ID를 문구에서 제거", sid, block_id))
        for phrase in OVERCLAIMS if part.type not in ("name", "link") else []:  # quoted titles are not our claims
            if phrase in text:
                add(Issue("OVERCLAIM", "block", f"근거보다 강한 단정 '{phrase}'", "허용 표현 범위로 수정", sid, block_id))

    # 3b. the client's own brands are never compared against each other in prose (PRD 핵심가치 1)
    if self_brands and len(self_brands) > 1:
        mentioned: dict[str, set[str]] = {}
        for block_id, _, part in _text_parts(slide):
            if part.type == "name" and part.text in self_brands:
                mentioned.setdefault(block_id, set()).add(part.text)
        for block_id, names in mentioned.items():
            if len(names) > 1:
                add(Issue("SELF_BRAND_COMPARISON", "block", f"자사 브랜드끼리 비교: {', '.join(sorted(names))}",
                          "문장에서 자사 브랜드 중 하나만 남기고 분리", sid, block_id))

    # 4. lead / commentary rules
    body_facts = set()
    for b in slide.blocks:
        if isinstance(b, TextBlock) and b.role == "lead":
            continue
        body_facts |= {bd.fact_id for bd in slide.bindings if bd.block_id.split("[")[0] == b.block_id}
    for b in slide.blocks:
        if not isinstance(b, TextBlock):
            continue
        if b.role == "lead":
            facts = [p.fact_id for para in b.paragraphs for p in para.parts if p.type == "fact"]
            if len(facts) > 2:
                add(Issue("LEAD_TOO_MANY_NUMBERS", "block", f"리드 숫자 {len(facts)}개(최대 2개)", "리드 축약", sid, b.block_id))
            outside = [f for f in facts if f not in body_facts]
            if outside:
                add(Issue("LEAD_CITES_HIDDEN", "block", "리드가 본문에 표시되지 않은 수치를 인용", "문장 수정 또는 본문 근거 추가",
                          sid, b.block_id))
        lines = sum(line_count(_paragraph_runs(p, b.weight, b.bold), _inner_width(b), b.size) for p in b.paragraphs) if b.paragraphs else 0
        if b.max_lines and lines > b.max_lines:
            add(Issue("TOO_MANY_LINES", "block", f"{b.role} {lines}줄(최대 {b.max_lines}줄)", "문장 축약 또는 분할",
                      sid, b.block_id))
        elif b.role in ("caption", "takeaway") and lines == 2:
            add(Issue("TWO_LINE_COMMENTARY", "warn", f"{b.role} 2줄", "검토 후 수용 가능", sid, b.block_id))
        needed = (lines * b.line_spacing + sum(p.space_before for p in b.paragraphs)) * 96 / 72
        if needed > b.region.h + 4:
            add(Issue("TEXT_OVERFLOW", "block", f"{b.role} 텍스트가 영역을 넘침({needed:.0f}>{b.region.h:.0f})",
                      "문장 축약·레이아웃 변경", sid, b.block_id))

    # 5. tables: cell overflow, row cap
    for b in slide.blocks:
        if isinstance(b, TableBlock):
            if len(b.rows) > tokens()["table_max_rows"]:
                add(Issue("TABLE_TOO_LONG", "block", f"표 {len(b.rows)}행", "표 분할", sid, b.block_id))
            total_w = sum(c.width for c in b.columns)
            for r_i, row in enumerate(b.rows):
                for c_i, (col, cell) in enumerate(zip(b.columns, row.cells)):
                    if cell.merged:
                        continue
                    width = b.region.w * col.width / total_w - 12
                    lines = sum(line_count(_paragraph_runs(p, None, cell.bold), width, b.size) for p in cell.paragraphs)
                    span = b.row_height * (1 + cell.merge_down)
                    if lines * b.size * 1.4 * 96 / 72 > span + 2:
                        add(Issue("CELL_OVERFLOW", "block", f"표 셀 텍스트 넘침 ({r_i + 1}행 {col.label})",
                                  "열 너비·행 분할 또는 축약", sid, f"{b.block_id}[{r_i},{c_i}]"))

    # 6. canvas bounds
    for b in slide.blocks:
        r = b.region
        if r.x < -0.5 or r.y < -0.5 or r.x + r.w > canvas["w"] + 0.5 or r.y + r.h > canvas["h"] + 0.5:
            add(Issue("OUT_OF_CANVAS", "block", "캔버스 밖 요소", "레이아웃 수정", sid, b.block_id))

    # 7. images
    for b in slide.blocks:
        if not isinstance(b, ImageBlock):
            continue
        asset = assets(b.asset_id)
        if asset is None or not Path(asset.path).exists():
            add(Issue("IMAGE_MISSING", "block", "이미지 파일 없음", "자산 복원 또는 페이지 제외", sid, b.block_id))
            continue
        if asset.review_status != "accepted":
            add(Issue("IMAGE_NOT_ACCEPTED", "block", "미채택 이미지", "이미지 채택 또는 교체", sid, b.block_id))
        c = b.crop
        if c.w <= 0 or c.h <= 0 or c.x < 0 or c.y < 0 or c.x + c.w > 1.0001 or c.y + c.h > 1.0001:
            add(Issue("BAD_CROP", "block", "잘못된 crop 좌표", "자르기 다시 지정", sid, b.block_id))
            continue
        px_w = asset.width * c.w
        if px_w < b.region.w * 0.9:
            add(Issue("LOW_RESOLUTION", "warn", f"이미지 해상도 낮음({px_w:.0f}px)", "고해상도 이미지로 교체 권장", sid, b.block_id))

    # 8. data slides need period/definition/source footnote
    if slide.is_data:
        foot = next((b for b in slide.blocks if isinstance(b, TextBlock) and b.role == "footnote"), None)
        has_date = foot and any(p.type == "date" for para in foot.paragraphs for p in para.parts)
        has_text = foot and any(p.rendered().strip("* ·") for para in foot.paragraphs for p in para.parts)
        if not foot or not has_date or not has_text:
            action = ("사례 카드에 발행일·활동일 또는 수치 측정일을 입력하세요" if slide.section_id == "campaign"
                      else "자료의 기간·측정일을 확인하세요")
            add(Issue("FOOTNOTE_MISSING", "block", "기간·출처 각주 누락", action, sid, "footnote"))
        partial = any(bd.formatter == "er" and bd.display.endswith("†") for bd in slide.bindings)
        if partial:
            add(Issue("PARTIAL_RATE", "warn", "좋아요 비공개 부분 반응률 포함(†)", "각주 정의 확인", sid, "footnote"))
            if foot and "†" not in "".join(p.rendered() for para in foot.paragraphs for p in para.parts):
                add(Issue("FOOTNOTE_MISSING", "block", "† 정의 각주 누락", "각주 추가", sid, "footnote"))
    if slide.needs_review and not frame:
        add(Issue("NEUTRAL_LEAD", "warn", "Finding 없는 중립 리드", "리드 문장 검토", sid, "lead"))


def _inner_width(b: TextBlock) -> float:
    if b.role == "takeaway":
        return b.region.w - 34
    return b.region.w


def _check_fact(sid: str, block_id: str, fact_id: Optional[str], formatter: Optional[str], display: Optional[str],
                registry: FactRegistry, add):
    obj = registry.get(fact_id) if fact_id else None
    if obj is None:
        add(Issue("FACT_UNLINKED", "block", f"Fact 미연결 수치({fact_id})", "근거 Fact 연결", sid, block_id))
        return
    if obj.confidence == "missing" or obj.value is None:
        add(Issue("FACT_MISSING", "block", "missing·미확인 수치 사용", "입력 보완", sid, block_id))
        return
    if isinstance(obj, Fact) and obj.verification_status != "eligible":
        add(Issue("FACT_NOT_ELIGIBLE", "block", "확인 전(candidate) 수치 사용", "자료 검토에서 채택", sid, block_id))
    if isinstance(obj, Fact) and obj.conflict_key:
        add(Issue("SOURCE_CONFLICT", "block", "제공자 간 값 충돌 수치", "값 선택", sid, block_id))
    if obj.confidence == "estimated":
        add(Issue("ESTIMATED_VALUE", "warn", "추정값 포함", "장표에 정의 표시 확인", sid, block_id))
    if formatter and display is not None:
        expected = format_value(formatter, obj.value, getattr(obj, "partial", False))
        if expected != display:
            add(Issue("VALUE_MISMATCH", "block", f"표시값 '{display}' ≠ 계산값 '{expected}'", "근거 Fact 수정 경로 이용",
                      sid, block_id))
