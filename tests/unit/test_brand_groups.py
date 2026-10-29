"""More than 3 self brands: side-by-side search slides continue on more pages instead of dropping brands."""
from core.composition.build import _brand_groups, _page_n
from core.composition.quant import QuantContext
from core.schemas.project import Project
from core.schemas.slidespec import SlideSpec


def ctx_with(n: int) -> QuantContext:
    p = Project.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"}, "enabled_slides": [],
        "brands": [{"id": f"B{i}", "name": f"자사{i}", "competitors": [f"경쟁{i}"]} for i in range(1, n + 1)]})
    return QuantContext(project=p, metrics=None, findings=[], pf=None, config=None, synthetic=False)


def test_up_to_three_brands_stay_on_one_page():
    assert [(n, len(c.project.brands)) for n, c in _brand_groups(ctx_with(3))] == [(1, 3)]


def test_more_brands_continue_on_numbered_pages():
    groups = _brand_groups(ctx_with(5))
    assert [(n, [b.id for b in c.project.brands]) for n, c in groups] == [(1, ["B1", "B2", "B3"]), (2, ["B4", "B5"])]
    s = SlideSpec(slide_id="2-8a", template_id="t", page_role="content", section_id="search", title="x", blocks=[])
    assert _page_n(s, 1).slide_id == "2-8a" and _page_n(s, 2).slide_id == "2-8a-2"
