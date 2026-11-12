"""P4-1 시장 수치 추출: 기간 해석, 원문 대조, 단위 복원, 보도자료 질의, MK1에서의 중복·출처 표시."""
from datetime import date
from decimal import Decimal

from app.services.market_figures import gov_queries, make_figure_fact, parse_period, validate_figures
from core.composition.build import BuildInputs, build_deck
from core.schemas.materials import CaseMaterial, ClaimRef, SourceRef
from tests.helpers import load_fixture
from tests.unit.test_five_axis import _market_fact

PAGE = ("작년 국민 출국자는 2,958만명으로 집계됐다. 러기지 시장은 연평균 7.0% 성장이 예상된다. "
        "1월 출국자는 326만 8천명이다.")


def test_parse_period_forms():
    assert parse_period("2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert parse_period("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert parse_period("2026-01~2026-08") == (date(2026, 1, 1), date(2026, 8, 31))
    assert parse_period("2026~2031") == (date(2026, 1, 1), date(2031, 12, 31))
    assert parse_period("") is None and parse_period("올해") is None and parse_period("2031~2026") is None


def test_validate_figures_checks_quotes_and_restores_units():
    figs, issues = validate_figures({"figures": [
        {"metric": "macro_indicator", "name": "국민 출국자 수", "value": "2958", "unit": "people", "period": "2025",
         "segment": "", "quote": "작년 국민 출국자는 2,958만명으로 집계됐다."},
        {"metric": "market_cagr", "name": "러기지 연평균 성장률", "value": "7.0", "unit": "percent", "period": "",
         "segment": "러기지", "quote": "러기지 시장은 연평균 7.0% 성장이 예상된다."},
        {"metric": "market_cagr", "name": "다른 값", "value": "9.0", "unit": "percent", "period": "", "segment": "",
         "quote": "러기지 시장은 연평균 7.0% 성장이 예상된다."},
        {"metric": "views", "name": "x", "value": "7.0", "unit": "percent", "period": "", "segment": "",
         "quote": "러기지 시장은 연평균 7.0% 성장이 예상된다."}]}, PAGE)
    assert [f["value"] for f in figs] == [Decimal("29580000"), Decimal("7.0")]
    assert figs[1]["period"] is None and len(issues) == 2

    fact = make_figure_fact(figs[0], brand_id="B1", entity="러기지", measured_at=date(2026, 11, 1), source="기사",
                            source_id="SRC-1", evidence_id="EV-1", url="https://example.com")
    assert fact.metric == "macro_indicator" and fact.unit == "people" and fact.verification_status == "candidate"
    assert fact.dims["indicator"] == "국민 출국자 수" and fact.period_end == date(2025, 12, 31)
    no_period = make_figure_fact(figs[1], brand_id="B1", entity="러기지", measured_at=date(2026, 11, 1), source="기사",
                                 source_id="SRC-1", evidence_id="EV-1", url=None)
    assert no_period.period_start == no_period.period_end == date(2026, 11, 1) and no_period.dims["segment"] == "러기지"


def test_million_dollar_figures_and_usd_display():
    from core.composition.formatters import format_value
    page = ("세계 러기지 및 백 시장 규모는 2024년 18,617백만 달러로 추정된다. The market reached USD 18.6 billion. "
            "백팩 시장 USD 23.12 십억")
    figs, _ = validate_figures({"figures": [
        {"metric": "market_size", "name": "세계 러기지 시장 규모", "value": "18617", "unit": "usd", "period": "2024",
         "segment": "", "quote": "세계 러기지 및 백 시장 규모는 2024년 18,617백만 달러로 추정된다."},
        {"metric": "market_size", "name": "world luggage", "value": "18.6", "unit": "usd", "period": "2024",
         "segment": "", "quote": "The market reached USD 18.6 billion."},
        {"metric": "market_size", "name": "백팩 시장", "value": "23.12", "unit": "usd", "period": "2026",
         "segment": "", "quote": "백팩 시장 USD 23.12 십억"}]}, page)
    assert [f["value"] for f in figs] == [Decimal("18617000000"), Decimal("18600000000.0"), Decimal("23120000000.00")]
    assert format_value("usd", figs[0]["value"]) == "186억 달러" and format_value("usd", Decimal(9900)) == "9,900달러"


def test_gov_queries_follow_the_industry():
    assert gov_queries("여행", "캐리어", 2026) == [
        "한국관광공사 국민 해외관광객 출국자 수 보도자료 2026",
        "문화체육관광부 국민여행조사 보도자료 2026",
    ]
    assert gov_queries(None, "백팩", 2026) == ["백팩 통계청 관세청 보도자료 2026"]


def test_mk1_prefers_p41_figures_and_names_press_releases_by_title():
    project, _, _ = load_fixture()
    project = project.model_copy(update={"enabled_slides": ["MK1"]})
    src = SourceRef(id="SRC-MKT-1", title="2026년 6월 한국관광통계 발표", url="https://kto.visitkorea.or.kr/news/1",
                    publisher="kto.visitkorea.or.kr", published_at=date(2026, 7, 30))
    m = CaseMaterial(id="MKT-1", brand_id="B1", entity="가방", section_id="market", title=src.title, source=src,
                     review_status="accepted",
                     claims=[ClaimRef(id="CL-1", kind="fact", parts=[{"type": "text", "text": "해외관광객 증가"}],
                                      review_status="accepted")])
    manual = _market_fact("percent", "6.2", "percent", label="가방 시장 연평균 성장률")  # same number, kept by hand
    p41 = [_market_fact("market_cagr", "6.2", "percent", segment="가방"),
           _market_fact("market_size", 2_987_000_000_000, "krw", segment="가방")]
    m.metric_fact_ids = [manual.id]
    r = build_deck(BuildInputs(project=project, facts=[manual, *p41], materials=[m], generated_on=date(2026, 10, 12)))
    mk1 = next(s for s in r.deck.slides if s.slide_id == "MK1")
    values = [b for b in mk1.blocks if b.block_id.endswith("_value")]
    assert len(values) == 2  # the hand-kept 6.2% is not shown twice
    foot = "".join(p.rendered() for b in mk1.blocks if b.block_id == "footnote" for para in b.paragraphs for p in para.parts)
    assert "2026년 6월 한국관광통계 발표" in foot and "2026.07.30" in foot
    from core.composition.axes import GOV_HOST
    assert GOV_HOST.search("www.korea.kr".removeprefix("www.")) and GOV_HOST.search("know.tour.go.kr")
    assert not GOV_HOST.search("newsis.com")
