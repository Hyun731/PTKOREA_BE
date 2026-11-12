"""P4-4 리서치 5대 축 장표: MK1 시장 규모·성장, DM1 수요·시즌, PL1 정책·규제, CS1 소비자 인사이트, 5-3 구매 여정, 5-4 구매 상황 지도."""
from datetime import date
from decimal import Decimal

from pptx import Presentation

from core.composition.build import BuildInputs, build_deck
from core.quality.qc import run_qc
from core.rendering.pptx_renderer import render_deck
from core.schemas.facts import Fact
from core.schemas.materials import CaseMaterial, ClaimRef, SourceRef
from core.schemas.project import Project
from core.schemas.slidespec import BarChartBlock, LineChartBlock, TableBlock, TextBlock
from tests.helpers import load_fixture
from tests.unit.test_p3_chart_pages import _fact, _p3_facts, _voc

DAY = date(2026, 10, 12)
CAT = "가방"  # the fixture brand's first category


def _market_fact(metric, value, unit, *, segment=None, indicator=None, start=date(2025, 1, 1), end=date(2025, 12, 31),
                 evidence="MKT-1", label=None):
    dims = {k: v for k, v in {"segment": segment, "indicator": indicator,
                              "quote": "국내 가방 시장은 연평균 6.2% 성장할 전망이다."}.items() if v}
    key = f"{metric}-{segment or indicator or label}-{start}"
    return Fact(id=f"F-{key}", content_hash=key, brand_id="B1", entity=CAT, metric=metric, value=Decimal(str(value)),
                unit=unit, dims=dims, period_start=start, period_end=end, measured_at=DAY, source="시장 보고서",
                evidence_id=evidence, confidence="verified", verification_status="eligible", label=label)


def _market_material(i, aspect=None, title=None, *, claims=("국내 가방 시장 성장 전망",), effective=None):
    src = SourceRef(id=f"SRC-MKT-{i}", title=title or f"시장 자료 {i}", url=f"https://example.com/market/{i}",
                    publisher="예시 리서치", published_at=date(2026, 3, i + 1))
    return CaseMaterial(
        id=f"MKT-{i}", brand_id="B1", entity=CAT, section_id="market", title=title or f"시장 자료 {i}", source=src,
        activity_date=effective, market_aspect=aspect, review_status="accepted",
        claims=[ClaimRef(id=f"CL-MKT-{i}-{j}", kind="interpretation" if j else "fact",
                         parts=[{"type": "text", "text": t}], review_status="accepted") for j, t in enumerate(claims)])


def _market_facts():
    facts = [_market_fact("market_size", 2_987_000_000_000, "krw", segment="국내 가방"),
             _market_fact("market_cagr", "6.2", "percent", segment="국내 가방", end=date(2030, 12, 31)),
             _market_fact("market_cagr", "9.1", "percent", segment="프리미엄 캐리어", end=date(2030, 12, 31))]
    for i, (month, value) in enumerate([(1, 2_400_000), (2, 2_250_000), (3, 2_310_000), (4, 2_280_000), (5, 2_340_000)]):
        facts.append(_market_fact("macro_indicator", value, "people", indicator="국민 해외관광객 수",
                                  start=date(2026, month, 1), end=date(2026, month, 28)))
    return facts


def _project(slides, brands=None):
    project, _, _ = load_fixture()
    update = {"enabled_slides": slides}
    if brands:
        update["brands"] = brands
    return project.model_copy(update=update)


def _build(project, facts=(), materials=(), synthesis=None):
    return build_deck(BuildInputs(project=project, facts=list(facts), materials=list(materials), generated_on=DAY,
                                  synthesis=synthesis or {}))


def _texts(slide) -> str:
    out = []
    for b in slide.blocks:
        if isinstance(b, TextBlock):
            out += ["".join(p.rendered() for para in b.paragraphs for p in para.parts)]
        elif isinstance(b, TableBlock):
            out += ["".join(x.rendered() for r in b.rows for c in r.cells for p in c.paragraphs for x in p.parts)]
    return " ".join(out)


def _blocks_qc(result, ids):
    qc = run_qc(result.deck, result.metrics.registry, lambda a: None, frozenset({"브랜드A", "브랜드B"}))
    return [i for i in qc.issues if i.severity == "block" and i.slide_id in ids]


# ---------------------------------------------------------------- MK1

def test_mk1_big_figures_macro_line_and_growth_lead():
    materials = [_market_material(1, "size_growth"), _market_material(2, "size_growth"), _market_material(3, "channel")]
    r = _build(_project(["M1"]), _market_facts(), materials)  # MK1 follows M1
    mk1 = next(s for s in r.deck.slides if s.slide_id == "MK1")
    assert mk1.chapter == "competitor" and mk1.is_data
    lead = next(b for b in mk1.blocks if b.block_id == "lead_claim")
    assert any(p.type == "fact" and p.display == "6.2%" for p in lead.paragraphs[0].parts)  # '연 6.2% 성장'
    assert "가방 시장, 연 6.2% 성장 전망" == "".join(p.rendered() for p in lead.paragraphs[0].parts)
    tiles = [b for b in mk1.blocks if b.block_id.endswith("_value")]
    assert len(tiles) == 3 and all(any(p.type == "fact" for p in t.paragraphs[0].parts) for t in tiles)
    line = next(b for b in mk1.blocks if isinstance(b, LineChartBlock))
    assert len(line.series[0].points) == 5 and all(p.fact_id for p in line.series[0].points)
    foot = _texts(mk1)
    assert "예시 리서치" in foot and "출처 1곳" in foot  # source and n
    assert {b.fact_id for b in mk1.bindings} >= {f.id for f in _market_facts()}
    assert not _blocks_qc(r, {"MK1"})


def test_mk1_needs_two_figures_and_reads_manual_card_figures():
    one = [_market_fact("market_cagr", "6.2", "percent", segment="국내 가방")]
    r = _build(_project(["MK1"]), one, [_market_material(1)])
    slot = next(p for p in r.deck.plan if p.slot_id == "MK1")
    assert slot.readiness == "thin" and "시장·타겟 근거" in slot.reason
    # Before P4-1: person-checked figures on a market card count when their name says what they are.
    manual = [_market_fact("percent", "7.0", "percent", label="세계 러기지 시장 연평균 성장률(2025~2031)"),
              _market_fact("percent", "15", "percent", label="스마트 러기지 시장 CAGR", start=date(2024, 1, 1)),
              _market_fact("percent", "41", "percent", label="북미 매출 비중", start=date(2023, 1, 1))]
    m = _market_material(1)
    m.metric_fact_ids = [f.id for f in manual]
    r = _build(_project(["MK1"]), manual, [m])
    mk1 = next(s for s in r.deck.slides if s.slide_id == "MK1")
    assert "41%" not in _texts(mk1) and "7%" in _texts(mk1) and "15%" in _texts(mk1)
    assert not any(isinstance(b, LineChartBlock) for b in mk1.blocks)  # no indicator: figures take the width
    assert not _blocks_qc(r, {"MK1"})


# ---------------------------------------------------------------- PL1

def test_pl1_splits_policy_rows_out_of_m1():
    materials = [_market_material(i, "size_growth") for i in (1, 2, 3)] + [
        _market_material(4, "policy", "면세 한도 상향", claims=("여행객 면세 한도 상향", "해외 구매 부담 완화"),
                         effective=date(2026, 7, 1)),
        _market_material(5, "policy", "소액 수입 기준 변경", claims=("소액 수입 면세 기준 조정",))]
    r = _build(_project(["M1", "PL1"]), [], materials)
    pages = {s.slide_id: s for s in r.deck.slides}
    pl1, m1 = pages["PL1"], pages["M1"]
    table = next(b for b in pl1.blocks if isinstance(b, TableBlock))
    assert [c.label for c in table.columns] == ["이슈", "기관·출처", "시행·발표일", "영향"]
    assert len(table.rows) == 2 and "시행 2026.07.01" in _texts(pl1) and "발표 2026.03.06" in _texts(pl1)
    m1_table = next(b for b in m1.blocks if isinstance(b, TableBlock))
    assert {r.ref for r in m1_table.rows} == {"MKT-1", "MKT-2", "MKT-3"}  # policy rows moved to PL1
    assert any(b.block_id == "insight0_title" for b in pl1.blocks)
    assert not _blocks_qc(r, {"PL1", "M1"})


def test_pl1_with_one_policy_note_stays_in_m1():
    materials = [_market_material(i, "size_growth") for i in (1, 2, 3)] + [_market_material(4, "policy", "면세 한도 상향")]
    r = _build(_project(["M1", "PL1"]), [], materials)
    assert "PL1" not in {s.slide_id for s in r.deck.slides}
    assert next(p for p in r.deck.plan if p.slot_id == "PL1").readiness == "thin"
    m1_table = next(b for b in next(s for s in r.deck.slides if s.slide_id == "M1").blocks if isinstance(b, TableBlock))
    assert "MKT-4" in {row.ref for row in m1_table.rows}


# ---------------------------------------------------------------- DM1

def test_dm1_reuses_the_demand_page_once():
    r = _build(_project(["TR1", "SH1"]), _p3_facts())
    ids = [s.slide_id for s in r.deck.slides]
    assert "DM1" in ids and "SH1" not in ids  # DM1 follows TR1 and takes SH1's place
    dm1 = next(s for s in r.deck.slides if s.slide_id == "DM1")
    assert dm1.chapter == "competitor" and any(isinstance(b, LineChartBlock) for b in dm1.blocks)


# ---------------------------------------------------------------- CS1

def _cs_facts(generations=False):
    facts = [f for f in _p3_facts() if f.metric == "pain_point_count"]
    facts.append(_fact("pain_point_count", 6, pain_point="지퍼 고장", n=40))
    for topic, value in (("price", 40), ("quality", 30), ("design", 20), ("other", 10)):
        facts.append(_fact("voc_topic_share", value, topic=topic, n=40))
    if generations:
        for gen, values in (("20대", (45, 30, 25)), ("30대", (30, 45, 25)), ("40대", (20, 50, 30))):
            for factor, value in zip(("디자인", "내구성", "가격"), values):
                facts.append(_fact("purchase_factor_share", value, generation=gen, factor=factor, n=60))
    return facts


def test_cs1_factors_pain_points_and_quotes():
    materials = [_voc("V1", "negative"), _voc("V2", "negative"), _voc("V3", "positive")]
    r = _build(_project(["5-1"]), _cs_facts(), materials)  # CS1 follows 5-1
    cs1 = next(s for s in r.deck.slides if s.slide_id == "CS1")
    charts = [b for b in cs1.blocks if isinstance(b, BarChartBlock)]
    assert [c.block_id for c in charts] == ["factors", "pains"]
    assert [it.label for it in charts[0].items] == ["가격", "품질", "디자인"]  # '기타' is not a factor
    assert len(charts[1].items) == 4 and cs1.chapter == "customer"
    assert any(b.block_id.startswith("quote") for b in cs1.blocks) and "n=40" in _texts(cs1)
    assert not _blocks_qc(r, {"CS1"})


def test_cs1_generation_factors_and_thin_data():
    r = _build(_project(["CS1"]), _cs_facts(generations=True), [_voc("V1", "negative")])
    cs1 = next(s for s in r.deck.slides if s.slide_id == "CS1")
    factors = next(b for b in cs1.blocks if b.block_id == "factors")
    assert factors.multi and [s.name for s in factors.series] == ["20대", "30대", "40대"]
    assert not _blocks_qc(r, {"CS1"})
    # fewer than three pain points: no page
    thin = [f for f in _cs_facts() if not (f.metric == "pain_point_count" and f.value < 12)]
    r = _build(_project(["CS1"]), thin, [_voc("V1", "negative")])
    assert "CS1" not in {s.slide_id for s in r.deck.slides}


def test_cs1_one_self_brand_per_page():
    project, _, _ = load_fixture()
    b2 = project.brands[0].model_copy(update={"id": "B2", "name": "브랜드B", "competitors": ["경쟁Z"]})
    facts = _cs_facts() + [f.model_copy(update={"id": f.id + "-b2", "brand_id": "B2", "entity": "브랜드B"})
                           for f in _cs_facts()]
    r = _build(_project(["CS1"], [project.brands[0], b2]), facts, [])
    pages = [s for s in r.deck.slides if s.slide_id.startswith("CS1")]
    assert sorted(s.slide_id for s in pages) == ["CS1-B1", "CS1-B2"]
    for s in pages:
        text = _texts(s)
        assert ("브랜드A" in text) != ("브랜드B" in text)
    assert not _blocks_qc(r, {s.slide_id for s in pages})


# ---------------------------------------------------------------- 5-3 · 5-4 (종합 AI 결과)

JOURNEY = {"lead": "검색에서 비교하다 가격에서 멈추는 여정", "stages": [
    {"stage": "인지", "touchpoint": "인스타그램 광고, 지인 추천", "state": "브랜드는 알지만 차이를 모름", "drop": "", "ref": "2-1"},
    {"stage": "탐색", "touchpoint": "블로그 후기, 쇼핑 검색", "state": "후기와 가격을 나란히 비교", "drop": "실사용 후기 부족", "ref": "BL1"},
    {"stage": "구매", "touchpoint": "공식몰, 백화점", "state": "할인 시점을 기다림", "drop": "가격 부담", "ref": "PP1"}]}
SITUATION = {"lead": "여행 직전 급하게 고를 때 경쟁 브랜드와 함께 고민", "rows": [
    {"situation": "첫 해외여행 준비", "brands": ["브랜드A", "경쟁X"],
     "pick": {"text": "튼튼해서 오래 쓴다", "url": "https://example.com/V1", "site": "네이버 카페", "date": "2026-05-01"},
     "skip": {"text": "가격이 너무 높다", "url": "https://example.com/V2", "site": "지식iN", "date": "2026-06-02"}},
    {"situation": "출장용 기내 가방", "brands": ["브랜드A", "경쟁Y"],
     "pick": {"text": "바퀴가 조용하다", "url": "https://example.com/V3", "site": "블로그", "date": "2026-04-03"},
     "skip": None}]}


def test_journey_and_situation_pages_from_synthesis(tmp_path):
    r = _build(_project(["5-1"]), [], [], synthesis={"B1": {"journey": JOURNEY, "situation": SITUATION}})
    pages = {s.slide_id: s for s in r.deck.slides}
    journey, situation = pages["5-3"], pages["5-4"]
    jt = next(b for b in journey.blocks if isinstance(b, TableBlock))
    assert [c.label for c in jt.columns] == ["단계", "접점", "소비자 상태", "끊기는 곳"] and len(jt.rows) == 3
    st = next(b for b in situation.blocks if isinstance(b, TableBlock))
    assert [c.label for c in st.columns][2:] == ["고르는 이유(원문)", "안 고르는 이유(원문)"]
    assert st.rows[0].cells[2].paragraphs[0].parts[0].type == "quote"
    assert "원문 3건" in _texts(situation)
    assert journey.chapter == situation.chapter == "customer"
    assert not _blocks_qc(r, {"5-3", "5-4"})
    assert _build(_project(["5-1"]), synthesis={"B1": {"journey": {"stages": JOURNEY["stages"][:2]}}}).deck.slides == []


def test_five_axis_pages_render(tmp_path):
    materials = [_market_material(i, "size_growth") for i in (1, 2, 3)] + [
        _market_material(4, "policy", "면세 한도 상향", claims=("여행객 면세 한도 상향", "해외 구매 부담 완화"),
                         effective=date(2026, 7, 1)),
        _market_material(5, "policy", "소액 수입 기준 변경", claims=("소액 수입 면세 기준 조정",)),
        _voc("V1", "negative"), _voc("V2", "positive")]
    r = _build(_project(["M1", "TR1", "5-1"]), _market_facts() + _p3_facts() + _cs_facts(), materials,
               synthesis={"B1": {"journey": JOURNEY, "situation": SITUATION}})
    ids = {s.slide_id for s in r.deck.slides}
    assert {"MK1", "DM1", "PL1", "CS1", "5-3", "5-4"} <= ids
    assert not _blocks_qc(r, ids)
    path = render_deck(r.deck, tmp_path / "axes.pptx")
    assert len(Presentation(str(path)).slides) == len(r.deck.slides)
