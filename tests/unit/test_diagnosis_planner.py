"""P5-1 진단 플래너: 입력 모으기와 서버 검증 규칙(없는 id, 근거 없는 주장·제안, 차트 유형, 자사 브랜드 비교)."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import diagnosis as dg
from core.composition.build import BuildInputs
from core.schemas.diagnosis import Diagnosis, DiagnosisVersion, active_data
from core.schemas.facts import Fact
from core.schemas.project import Brand
from tests.helpers import load_fixture
from tests.unit.test_p3_chart_pages import DAY, _p3_facts, _voc


def _inputs(extra_facts=(), brands=None):
    project, facts, posts = load_fixture()
    if brands:
        project = project.model_copy(update={"brands": brands})
    materials = [_voc("V1", "negative", title="바퀴 소리가 너무 커요"), _voc("V2", "positive", title="튼튼해서 오래 써요")]
    return BuildInputs(project=project, facts=[*facts.facts, *posts.facts, *_p3_facts(), *extra_facts],
                       posts=posts.posts, materials=materials, generated_on=DAY)


@pytest.fixture(scope="module")
def pi():
    return dg.gather(_inputs(), "B1")


def ref(pi, metric, entity=None, **dims) -> str:
    for f in pi.facts:
        if f["metric"] == metric and (entity is None or f["entity"] == entity) and all(
                f["dims"].get(k) == v for k, v in dims.items()):
            return f["ref"]
    raise KeyError((metric, entity, dims))


def seg(text="", fact_ref=None, accent=False):
    return {"text": text, "fact_ref": fact_ref, "accent": accent}


def good_answer(pi) -> dict:
    neg, pain1, pain2 = ref(pi, "voc_negative_rate", site="전체"), ref(pi, "pain_point_count", pain_point="바퀴 소음"), \
        ref(pi, "pain_point_count", pain_point="손잡이 불편")
    blog_a, blog_x = ref(pi, "mention_total", "브랜드A", channel="blog"), ref(pi, "mention_total", "경쟁X", channel="blog")
    share = ref(pi, "search_share", "브랜드A")
    q = {x["material_id"]: x["ref"] for x in pi.quotes}
    return {
        "profile": "검색 인지는 앞서고, 사용 후기에서 불편이 쌓이는 브랜드",
        "funnel": [{"stage": "검증", "fact_ref": neg, "label": "원문 부정 비율", "status": "이탈"},
                   {"stage": "인지", "fact_ref": share, "label": "브랜드명 검색 점유", "status": "강점"},
                   {"stage": "인지", "fact_ref": None, "label": "중복 단계", "status": "보통"},
                   {"stage": "탐색", "fact_ref": "F999", "label": "블로그 언급", "status": "보통"}],
        "claims": [
            {"kind": "strength", "claim": [seg("브랜드명 검색은 경쟁 세트 "), seg("선두", accent=True)],
             "evidence": [[seg("브랜드명 검색 점유 "), seg(fact_ref=share)]],
             "chart": {"type": "line", "fact_refs": [ref(pi, "search_share", e) for e in ("브랜드A", "경쟁X", "경쟁Y")]},
             "quote_refs": [q["V2"]]},
            {"kind": "weakness", "claim": [seg("사용 후기에서 "), seg("바퀴 소음", accent=True), seg(" 불편이 가장 많음")],
             "evidence": [[seg("바퀴 소음 원문 "), seg(fact_ref=pain1), seg("건")], [seg("'바퀴 소리가 너무 커요'")]],
             "chart": {"type": "stacked", "fact_refs": [pain1, pain2]}, "quote_refs": [q["V1"], "Q77"]},
            {"kind": "weakness", "claim": [seg("블로그 언급량은 경쟁X보다 "), seg("적음", accent=True)],
             "evidence": [[seg("블로그 언급 "), seg(fact_ref=blog_a), seg(" vs 경쟁X "), seg(fact_ref=blog_x)]],
             "chart": {"type": "bar", "fact_refs": [blog_a, blog_x]}, "quote_refs": []},
            # dropped: an unknown number, a sentence with a bare digit, no evidence at all
            {"kind": "weakness", "claim": [seg("카페 언급 열세")], "evidence": [[seg("카페 "), seg(fact_ref="F999")]],
             "chart": {"type": "bar", "fact_refs": []}, "quote_refs": []},
            {"kind": "weakness", "claim": [seg("부정 후기 3건 중 1건이 소음")], "evidence": [[seg(fact_ref=neg)]],
             "chart": {"type": "bar", "fact_refs": []}, "quote_refs": []},
            {"kind": "weakness", "claim": [seg("손잡이 불편 반복")], "evidence": [],
             "chart": {"type": "bar", "fact_refs": []}, "quote_refs": []},
        ],
        "cdj": [{"stage": "탐색", "touchpoint": "블로그 후기", "state": "후기 비교", "activity": "실사용 후기 확대"},
                {"stage": "구매", "touchpoint": "공식몰", "state": "가격 망설임", "activity": "사은품 안내"},
                {"stage": "검증", "touchpoint": "커뮤니티", "state": "3년 사용 후기", "activity": "AS 안내"}],
        "proposals": [
            {"pillar": "콘텐츠", "title": "바퀴 소음 개선 비교 영상", "cdj_stage": "탐색", "basis_fact_refs": [pain1],
             "basis": [seg("바퀴 소음 원문 "), seg(fact_ref=pain1), seg("건")]},
            {"pillar": "소셜", "title": "후기 리그램 캠페인", "cdj_stage": "없는 단계", "basis_fact_refs": [blog_a],
             "basis": [seg("블로그 언급 "), seg(fact_ref=blog_a)]},
            {"pillar": "인플루언서", "title": "여행 크리에이터 협업", "cdj_stage": "탐색", "basis_fact_refs": [],
             "basis": [seg("근거 없음")]},
            {"pillar": "인플루언서", "title": "출장러 리뷰어 협업", "cdj_stage": "검증", "basis_fact_refs": ["F999"],
             "basis": [seg("부정 비율 "), seg(fact_ref=neg)]},
        ],
    }


def test_gather_lists_brand_facts_quotes_and_findings(pi):
    assert pi.facts[0]["ref"] == "F1" and all(f["fact_id"] and f["display"] for f in pi.facts)
    assert {"voc_negative_rate", "pain_point_count", "search_share", "mention_total"} <= {f["metric"] for f in pi.facts}
    assert not any(f["metric"] in ("search_share_rank", "ad_candidate") for f in pi.facts)  # helper values stay out
    assert [q["material_id"] for q in pi.quotes] and {q["ref"] for q in pi.quotes} == {"Q1", "Q2"}
    assert pi.findings  # rule findings are shown as hints
    prompt = dg.user_prompt(pi, "약점을 먼저")
    assert "<brand>브랜드A</brand>" in prompt and "F1:" in prompt and "<request>\n약점을 먼저" in prompt
    assert dg.input_fingerprint(pi) == dg.input_fingerprint(dg.gather(_inputs(), "B1"))


def test_gather_never_shows_another_self_brand():
    project, _, _ = load_fixture()
    b2 = Brand(id="B2", name="브랜드B", categories=["가방"], target=project.brands[0].target, competitors=["경쟁X"])
    other = Fact(id="F-other-self", content_hash="o", brand_id="B1", entity="브랜드B", metric="mention_total",
                 value=Decimal(500), unit="count", dims={"channel": "blog"}, period_start=date(2026, 1, 1),
                 period_end=date(2026, 9, 30), measured_at=DAY, source="synthetic_fixture", confidence="verified",
                 verification_status="eligible")
    pi = dg.gather(_inputs([other], brands=[project.brands[0], b2]), "B1")
    assert "F-other-self" not in {f["fact_id"] for f in pi.facts}


def test_clean_keeps_only_cited_claims_and_fixes_charts(pi):
    out, issues = dg.clean(good_answer(pi), pi)
    assert out.profile.startswith("검색 인지는")
    assert [s.stage for s in out.funnel] == ["인지", "탐색", "검증"]  # canonical order, one per stage
    assert out.funnel[1].fact_id is None and any("F999" in i for i in issues)  # an unknown number is not kept
    assert out.funnel[0].fact_id == pi.by_ref[ref(pi, "search_share", "브랜드A")]["fact_id"]

    assert [(c.id, c.kind) for c in out.claims] == [("c1", "strength"), ("c2", "weakness"), ("c3", "weakness")]
    strength, noise, blog = out.claims
    facts = [p for p in strength.evidence[0].parts if p.type == "fact"]
    assert facts and facts[0].display  # numbers only as formatted fact parts
    assert strength.chart.type == "bar"  # not a time series: line is not allowed
    assert noise.chart.type == "bar"  # counts, one entity: nothing to stack
    assert noise.quote_material_ids == ["V1"] and any("Q77" in i for i in issues)
    assert blog.chart.type == "bar" and len(blog.chart.fact_ids) == 2
    dropped = [i for i in issues if "뺌" in i]
    assert len([i for i in dropped if i.startswith("주장")]) == 3  # unknown ref, bare digit, no evidence

    assert [r.stage for r in out.cdj] == ["탐색", "구매"]  # '3년' has a digit
    assert [(p.pillar, p.title) for p in out.proposals] == [("소셜", "후기 리그램 캠페인"),
                                                            ("콘텐츠", "바퀴 소음 개선 비교 영상")]
    assert out.proposals[0].cdj_stage is None and out.proposals[1].cdj_stage == "탐색"
    assert all(p.basis_fact_ids and any(x.type == "fact" for x in p.basis[0].parts) for p in out.proposals)


def test_fix_chart_rules(pi):
    months = [f for f in pi.facts if f["metric"] == "shop_click_index" and f["entity"] == "캐리어"]
    assert len(months) == 4
    line = dg.fix_chart("line", list(reversed(months)), 4)
    assert line.type == "line" and line.fact_ids == [f["fact_id"] for f in months]  # sorted by month
    assert dg.fix_chart("line", months[:3], 4).type == "column"  # a short series: columns
    assert dg.fix_chart("bar", months[:1], 4) is None  # one value is not a chart
    mixed = months[:2] + [f for f in pi.facts if f["unit"] == "percent"][:1]
    assert len(dg.fix_chart("bar", mixed, 4).fact_ids) == 2  # one unit per chart
    shares = [{"fact_id": f"S{i}", "unit": "percent", "entity": e, "metric": "comment_sentiment_rate",
               "dims": {"polarity": p}, "series_key": f"{e}{p}", "when": None}
              for i, (e, p) in enumerate([("A", "긍정"), ("A", "부정"), ("X", "긍정"), ("X", "부정")])]
    assert dg.fix_chart("stacked", shares, 4).type == "stacked"
    assert dg.fix_chart("stacked", shares[:2], 4).type == "bar"  # one entity: plain bars


def test_self_brand_comparison_is_dropped():
    project, _, _ = load_fixture()
    b2 = Brand(id="B2", name="브랜드B", categories=["가방"], target=project.brands[0].target, competitors=["경쟁X"])
    pi = dg.gather(_inputs(brands=[project.brands[0], b2]), "B1")
    share = ref(pi, "search_share", "브랜드A")
    answer = {"profile": "브랜드B보다 앞선 인지", "funnel": [], "cdj": [], "proposals": [], "claims": [
        {"kind": "strength", "claim": [seg("브랜드A가 브랜드B보다 검색 우위")], "evidence": [[seg("점유 "), seg(fact_ref=share)]],
         "chart": {"type": "bar", "fact_refs": []}, "quote_refs": []}]}
    out, issues = dg.clean(answer, pi)
    assert out.claims == [] and out.profile == ""
    assert any("자사 브랜드끼리 비교" in i for i in issues)


def test_plan_asks_again_with_reasons_then_keeps_what_passes(pi):
    calls = []
    first = good_answer(pi)
    first["claims"] = first["claims"][3:]  # only broken claims

    def call(user, attempt, note):
        calls.append(note)
        return first if attempt == 0 else good_answer(pi)

    out, issues = dg.plan(pi, call)
    assert len(calls) == 2 and calls[0] == "" and "이전 답의 문제" in calls[1]
    assert len(out.shown_claims("strength")) == 1 and len(out.shown_claims("weakness")) == 2
    empty = dg.PlannerInput(brand=pi.brand, self_names=pi.self_names, facts=[], quotes=[], cases=[], findings=[],
                            metrics=pi.metrics, pf=pi.pf)
    with pytest.raises(ValueError):
        dg.plan(empty, call)


def test_versions_are_kept_per_brand_and_one_is_active():
    project = SimpleNamespace(diagnosis=None)
    d1 = Diagnosis(profile="첫 진단")
    v1 = dg.save_version(project, "B1", DiagnosisVersion(version=0, fp="a", data=d1))
    v2 = dg.save_version(project, "B1", DiagnosisVersion(version=0, fp="b", data=Diagnosis(profile="둘째")))
    dg.save_version(project, "B2", DiagnosisVersion(version=0, fp="c", data=Diagnosis(profile="다른 브랜드")))
    assert (v1.version, v2.version) == (1, 2) and v2.created_at
    assert active_data(project.diagnosis) == {"B1": v2.data.model_dump(mode="json"),
                                              "B2": Diagnosis(profile="다른 브랜드").model_dump(mode="json")}
    dg.set_active(project, "B1", 1)
    assert dg.active_version(project, "B1").data.profile == "첫 진단"
    with pytest.raises(KeyError):
        dg.set_active(project, "B1", 9)
    for _ in range(dg.KEEP_VERSIONS + 3):
        dg.save_version(project, "B1", DiagnosisVersion(version=0, data=Diagnosis()))
    active, vs = dg.versions(project, "B1")
    assert len(vs) == dg.KEEP_VERSIONS and active == vs[-1].version
