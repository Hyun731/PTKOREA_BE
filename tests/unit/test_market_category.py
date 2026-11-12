"""Phase 3-2 산업 카테고리 분석(M1): 카테고리가 같으면 브랜드 비교 장처럼 한 번만, 다르면 브랜드마다 따로."""
from datetime import date

from core.composition.build import BuildInputs, _market_by_category, build_deck
from core.composition.chrome import PartFactory
from core.composition.quant import QuantContext
from core.metrics.registry import FactRegistry
from core.rules.config import RulesConfig
from core.schemas.materials import CaseMaterial, ClaimRef, SourceRef
from core.schemas.project import Project


def _brands(cats: list[str]) -> Project:
    p = Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"}, "enabled_slides": ["M1"],
        "brands": [{"id": f"B{i + 1}", "name": f"자사{i + 1}", "competitors": [f"경쟁{i + 1}"], "categories": [c]}
                  for i, c in enumerate(cats)]})
    return p


def _ctx(project) -> QuantContext:
    return QuantContext(project, None, [], PartFactory(FactRegistry()), RulesConfig.load(), False)


def _market_material(idx: int, category: str) -> CaseMaterial:
    src = SourceRef(id=f"SRC-{idx}", title=f"출처 {idx}")
    claims = [ClaimRef(id=f"CL-{idx}", kind="fact", parts=[], review_status="accepted")]
    return CaseMaterial(id=f"EV-{idx}", section_id="market", entity=category, title=f"항목 {idx}", source=src,
                        claims=claims, review_status="accepted")


def _run(project, materials):
    calls = []

    def fake_slot(slot_id, template, slides, reason, label=None, part=None, key=None, density=None):
        calls.append({"slot_id": slot_id, "label": label, "part": part, "slides": slides, "density": density})

    _market_by_category(_ctx(project), materials, {"M1"}, fake_slot, [], None)
    return calls


def test_shared_category_builds_once_unscoped():
    brands = _brands(["러기지", "러기지"])
    calls = _run(brands, [_market_material(1, "러기지")])
    assert len(calls) == 1
    assert calls[0]["part"] is None  # 두 브랜드가 같은 카테고리 — 브랜드 비교 장처럼 한 번만
    assert len(calls[0]["slides"]) == 1


def test_different_categories_build_separately_per_brand():
    brands = _brands(["러기지", "뷰티"])
    materials = [_market_material(1, "러기지"), _market_material(2, "뷰티")]
    calls = _run(brands, materials)
    assert len(calls) == 2
    assert {c["part"] for c in calls} == {"B1", "B2"}
    assert all(len(c["slides"]) == 1 for c in calls)  # 서로 다른 카테고리의 자료가 섞이지 않음
    assert all(c["label"] for c in calls)  # 카테고리가 여럿이면 구분되는 라벨


def test_no_market_materials_still_reports_missing_once():
    calls = _run(_brands(["러기지", "러기지"]), [])
    assert len(calls) == 1 and calls[0]["slides"] == []  # 자료가 없어도 needs_input은 한 번만


def test_market_slide_not_enabled_is_skipped():
    calls = []
    _market_by_category(_ctx(_brands(["러기지"])), [_market_material(1, "러기지")], set(),
                        lambda *a, **k: calls.append(1), [], None)
    assert calls == []


def test_market_page_requires_three_matching_evidence_items():
    project = Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "enabled_slides": ["M1"],
        "brands": [{"id": "B1", "name": "자사1", "competitors": ["경쟁1"], "categories": ["러기지"]}],
    })
    result = build_deck(BuildInputs(project=project, facts=[],
                                    materials=[_market_material(1, "러기지"), _market_material(2, "러기지")],
                                    generated_on=date(2026, 10, 12)))
    slot = next(s for s in result.deck.plan if s.template_id == "M1")
    assert slot.readiness == "thin" and not result.deck.slides

    result = build_deck(BuildInputs(project=project, facts=[],
                                    materials=[_market_material(i, "러기지") for i in range(1, 4)],
                                    generated_on=date(2026, 10, 12)))
    assert next(s for s in result.deck.plan if s.template_id == "M1").readiness == "ready"


def test_market_page_rejects_evidence_from_another_category():
    project = Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "enabled_slides": ["M1"],
        "brands": [{"id": "B1", "name": "자사1", "competitors": ["경쟁1"], "categories": ["러기지"]}],
    })
    result = build_deck(BuildInputs(project=project, facts=[],
                                    materials=[_market_material(i, "뷰티") for i in range(1, 4)],
                                    generated_on=date(2026, 10, 12)))
    assert next(s for s in result.deck.plan if s.template_id == "M1").readiness == "needs_input"
