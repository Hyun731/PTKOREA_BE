"""P1-1: 여러 계열·세로·누적 막대 차트 (스키마 검증, 렌더러, 바인딩, QC, 편집 문맥)."""
from datetime import date
from decimal import Decimal

import pytest
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE

from core.composition.build import _bindings
from core.composition.chrome import PartFactory
from core.composition.formatters import format_value
from core.editing.scope import element_info
from core.metrics.engine import MetricsResult
from core.metrics.registry import FactRegistry
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.facts import Fact
from core.schemas.slidespec import BarChartBlock, BarItem, BarSeries, DeckSpec, Region, SlideSpec

CATS = ["블로그", "카페", "뉴스"]
VALUES = {"자사": [40, 25, None], "경쟁사A": [55, 12, 8]}


def _fact(fid: str, value: int) -> Fact:
    return Fact(id=fid, content_hash=fid, brand_id="B1", entity=fid.split(":")[0], metric="mention_total",
                value=Decimal(value), unit="count", period_start=date(2026, 1, 1), period_end=date(2026, 9, 30),
                measured_at=date(2026, 9, 30), source="test", confidence="verified", verification_status="eligible")


def _item(entity: str, cat: str, v: int) -> BarItem:
    return BarItem(entity=entity, label=cat, fact_id=f"{entity}:{cat}", display=format_value("count", Decimal(v)),
                   value=v, formatter="count")


def _series() -> list[BarSeries]:
    return [BarSeries(name=e, role="self" if e == "자사" else "key",
                      items=[_item(e, c, v) if v is not None else None for c, v in zip(CATS, vals)])
            for e, vals in VALUES.items()]


def _chart(orientation="h", stacked=False) -> BarChartBlock:
    return BarChartBlock(block_id="chart", region=Region(x=40, y=120, w=600, h=300), categories=CATS,
                         series=_series(), orientation=orientation, stacked=stacked, number_format="0")


def _registry() -> FactRegistry:
    return FactRegistry([_fact(f"{e}:{c}", v) for e, vals in VALUES.items() for c, v in zip(CATS, vals) if v is not None])


def _slide(*blocks) -> SlideSpec:
    return SlideSpec(slide_id="s1", template_id="t", page_role="content", title="t", blocks=list(blocks))


def _deck(*blocks) -> DeckSpec:
    return DeckSpec(deck_id="d", deck_version=1, project_name="p", template_version="1", slides=[_slide(*blocks)],
                    plan=[], input_fingerprint="x")


def test_schema_rejects_mixed_or_misaligned_layouts():
    one = _item("자사", "블로그", 1)
    with pytest.raises(ValueError, match="하나만"):
        BarChartBlock(block_id="c", region=Region(x=0, y=0, w=1, h=1), items=[one], categories=["a"],
                      series=[BarSeries(name="s", items=[one])])
    with pytest.raises(ValueError, match="범주"):
        BarChartBlock(block_id="c", region=Region(x=0, y=0, w=1, h=1), categories=["a", "b"],
                      series=[BarSeries(name="s", items=[one])])
    with pytest.raises(ValueError, match="누적"):
        BarChartBlock(block_id="c", region=Region(x=0, y=0, w=1, h=1), items=[one], stacked=True)


def test_bar_items_skips_empty_cells():
    chart = _chart()
    assert chart.multi
    assert len(chart.bar_items()) == 5  # 6 cells, one None


@pytest.mark.parametrize("orientation,stacked,expected", [
    ("h", False, XL_CHART_TYPE.BAR_CLUSTERED), ("h", True, XL_CHART_TYPE.BAR_STACKED),
    ("v", False, XL_CHART_TYPE.COLUMN_CLUSTERED), ("v", True, XL_CHART_TYPE.COLUMN_STACKED),
])
def test_renders_native_chart_of_each_kind(tmp_path, orientation, stacked, expected):
    out = render_deck(_deck(_chart(orientation, stacked)), tmp_path / "c.pptx")
    shape = next(s for s in Presentation(out).slides[0].shapes if s.name == "chart")
    chart = shape.chart
    assert chart.chart_type == expected
    assert [s.name for s in chart.series] == list(VALUES)
    assert list(chart.plots[0].categories) == CATS
    assert list(chart.series[0].values) == [40, 25, None]  # missing cell stays blank, never 0
    assert chart.has_legend


def test_single_series_chart_still_renders_as_before(tmp_path):
    items = [_item("자사", "자사", 61), _item("경쟁사A", "경쟁사A", 43)]
    block = BarChartBlock(block_id="chart", region=Region(x=40, y=120, w=600, h=300), items=items)
    out = render_deck(_deck(block), tmp_path / "c.pptx")
    chart = next(s for s in Presentation(out).slides[0].shapes if s.name == "chart").chart
    assert chart.chart_type == XL_CHART_TYPE.BAR_CLUSTERED
    assert not chart.has_legend
    assert list(chart.series[0].values) == [61, 43]


def test_bindings_cover_every_series_with_its_formatter():
    reg = _registry()
    metrics = MetricsResult(registry=reg, share_tables=[], monthly=[], posts={}, ad={}, issues=[])
    out = _bindings(_slide(_chart()), metrics, PartFactory(reg))
    assert {b.fact_id for b in out} == {f"{e}:{c}" for e, vals in VALUES.items() for c, v in zip(CATS, vals) if v}
    assert {b.formatter for b in out} == {"count"}


def test_qc_checks_values_in_every_series():
    clean = run_qc(_deck(_chart()), _registry(), lambda a: None)
    assert not [i for i in clean.issues if i.block_id == "chart"]
    reg = _registry()
    del reg.facts["경쟁사A:뉴스"]  # an unsourced bar in the second series must still be caught
    issues = run_qc(_deck(_chart()), reg, lambda a: None).issues
    assert [i.code for i in issues if i.block_id == "chart"] == ["FACT_UNLINKED"]


def test_qc_catches_display_that_does_not_match_the_fact():
    chart = _chart()
    chart.series[1].items[0] = chart.series[1].items[0].model_copy(update={"display": "999"})
    issues = run_qc(_deck(chart), _registry(), lambda a: None).issues
    assert [i.code for i in issues if i.block_id == "chart"] == ["VALUE_MISMATCH"]


def test_edit_context_describes_series_and_layout():
    info = element_info(_chart("v", True))
    assert info["layout"] == "누적 세로 막대"
    assert "경쟁사A · 뉴스 8" in info["bars"]
    assert len(info["bars"]) == 5
