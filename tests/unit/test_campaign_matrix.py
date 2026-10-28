"""1-6 타겟·채널별 캠페인 매트릭스 (core/composition/overview.py)."""
from datetime import date

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.materials import CaseMaterial, SourceRef, TARGET_SEGMENTS
from core.schemas.slidespec import TableBlock
from tests.helpers import load_fixture


def _material(id_, brand_id, entity, segment, title):
    return CaseMaterial(id=id_, brand_id=brand_id, entity=entity, section_id="campaign", title=title,
                        event_name=title, source=SourceRef(id=f"SRC-{id_}", title=title),
                        review_status="accepted", target_segment=segment)


def _cell_text(cell):
    return "".join(p.rendered() for para in cell.paragraphs for p in para.parts)


def test_campaign_matrix_groups_self_brand_by_segment():
    project, _, _ = load_fixture()
    materials = [
        _material("EV1", "B1", "브랜드A", "대학생·Gen Z", "캠퍼스 팝업"),
        _material("EV2", "B1", "브랜드A", "대학생·Gen Z", "대학생 할인 이벤트"),
        _material("EV3", "B1", "브랜드A", "외국인 관광객", "인바운드 관광 프로모션"),
        _material("EV4", "B1", "경쟁X", "대학생·Gen Z", "경쟁사 캠퍼스 행사"),  # 경쟁사: 제외
        _material("EV5", "B1", "브랜드A", None, "분류 안 된 캠페인"),  # 타겟 미분류: 제외
    ]
    cfg = project.model_copy(update={"enabled_slides": ["1-6"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=materials, generated_on=date(2026, 10, 12)))
    slide = next(s for s in result.deck.slides if s.slide_id == "1-6")
    table = next(b for b in slide.blocks if isinstance(b, TableBlock))
    assert len(table.rows) == len(TARGET_SEGMENTS)

    genz_row = next(r for r in table.rows if _cell_text(r.cells[0]) == "대학생·Gen Z")
    cell = _cell_text(genz_row.cells[1])
    assert "캠퍼스 팝업" in cell and "[외부]" in cell
    all_text = "".join(_cell_text(c) for r in table.rows for c in r.cells)
    assert "경쟁사 캠퍼스 행사" not in all_text and "분류 안 된 캠페인" not in all_text

    empty_row = next(r for r in table.rows if _cell_text(r.cells[0]) == "직장인")
    assert _cell_text(empty_row.cells[1]) == "—"

    qc = run_qc(result.deck, result.metrics.registry, lambda a: None)
    blocking = [i for i in qc.issues if i.severity == "block" and i.slide_id == "1-6"]
    assert blocking == [], blocking


def test_campaign_matrix_absent_without_classified_materials():
    project, _, _ = load_fixture()
    cfg = project.model_copy(update={"enabled_slides": ["1-6"]})
    result = build_deck(BuildInputs(project=cfg, facts=[], materials=[], generated_on=date(2026, 10, 12)))
    assert not any(s.slide_id == "1-6" for s in result.deck.slides)
    slot = next(p for p in result.deck.plan if p.slot_id == "1-6")
    assert slot.readiness == "needs_input"
