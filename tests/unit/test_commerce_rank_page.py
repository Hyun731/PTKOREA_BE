"""CR1 판매 순위·후기 경쟁 장표 조합과 QC 회귀 테스트."""
from datetime import date
from decimal import Decimal

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.schemas.facts import Fact
from core.schemas.slidespec import TableBlock
from tests.helpers import load_fixture

DAY = date(2026, 11, 13)


def _fact(metric: str, value: int, entity: str, **dims) -> Fact:
    suffix = "-".join(f"{key}-{value}" for key, value in sorted(dims.items()))
    return Fact(
        id=f"F-{metric}-{entity}-{suffix}",
        content_hash="h",
        brand_id="B1",
        entity=entity,
        metric=metric,
        value=Decimal(value),
        unit="count",
        dims={key: str(value) for key, value in dims.items()},
        period_start=date(2026, 10, 15),
        period_end=DAY,
        measured_at=DAY,
        source="synthetic_fixture",
        confidence="verified",
        verification_status="eligible",
    )


def _rank_facts() -> list[Fact]:
    facts = []
    ranks = {
        "브랜드A": {"AGE_BAND_ALL": 20, "AGE_BAND_35": 8, "AGE_BAND_40": 4},
        "경쟁X": {"AGE_BAND_ALL": 1, "AGE_BAND_35": 1, "AGE_BAND_40": 16},
        "경쟁Y": {"AGE_BAND_ALL": 19, "AGE_BAND_35": 3, "AGE_BAND_40": 17},
    }
    for entity, bands in ranks.items():
        for band, rank in bands.items():
            dims = {"platform": "musinsa", "category": "carrier", "category_label": "캐리어",
                    "age_band": band}
            facts.append(_fact("commerce_ranked_items", rank % 9 + 2, entity, **dims))
            facts.append(_fact("commerce_best_rank", rank, entity, **dims))
        facts.append(_fact("commerce_top_reviews", 7565 if entity == "경쟁X" else 362, entity,
                           platform="musinsa"))
        facts.append(_fact("commerce_top_likes", 22088 if entity == "경쟁X" else 1356, entity,
                           platform="musinsa"))
    return facts


def test_cr1_builds_without_unbound_numbers_or_cell_overflow():
    project, _, _ = load_fixture()
    project = project.model_copy(update={"enabled_slides": ["CR1"]})
    result = build_deck(BuildInputs(project=project, facts=_rank_facts(), generated_on=DAY))

    assert [slide.slide_id for slide in result.deck.slides] == ["CR1"]
    slide = result.deck.slides[0]
    tables = [block for block in slide.blocks if isinstance(block, TableBlock)]
    assert len(tables) == 1

    qc = run_qc(result.deck, result.metrics.registry, lambda asset_id: None)
    codes = {issue.code for issue in qc.issues if issue.slide_id == "CR1"}
    assert "UNBOUND_NUMBER" not in codes
    assert "CELL_OVERFLOW" not in codes


def test_cr1_uses_metadata_for_out_of_rank_scope():
    facts = _rank_facts()
    dims = {"platform": "musinsa", "category": "carrier", "category_label": "캐리어",
            "age_band": "AGE_BAND_MINOR"}
    facts.extend([
        _fact("commerce_ranked_items", 0, "브랜드A", **dims),
        _fact("commerce_ranked_items", 0, "경쟁X", **dims),
    ])
    project, _, _ = load_fixture()
    project = project.model_copy(update={"enabled_slides": ["CR1"]})
    result = build_deck(BuildInputs(project=project, facts=facts, generated_on=DAY))

    table = next(block for block in result.deck.slides[0].blocks if isinstance(block, TableBlock))
    out_parts = [part for row in table.rows for cell in row.cells for para in cell.paragraphs for part in para.parts
                 if part.rendered() == "100위 밖"]
    assert out_parts and all(part.type == "meta" and part.key == "rank_out" for part in out_parts)
