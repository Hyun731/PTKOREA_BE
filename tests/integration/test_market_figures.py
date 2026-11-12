"""P4-1 시장·정책·업종 KPI 수치를 Fact로: 원문과 대조한 수치만 후보로, 자료를 채택하면 함께 채택."""
import pytest

from app.db import SessionLocal
from app.models import ProviderCache
from app.services import research
from integrations.base import CallResult
from integrations.fetch.page import Page
from tests.integration.test_research import fakes, item, ok, open_pending, setup_project  # noqa: F401 (fixture)

@pytest.fixture(autouse=True)
def _fresh_cache():
    """Answers cached here must not count as earlier calls in other modules' billing checks."""
    yield
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()


MARKET_PAGE = ("국내 여행가방 시장 규모는 2025년 2987억원으로 집계됐다. 업계는 2026년부터 2031년까지 연평균 6.2% 성장할 것으로 본다. "
               "한국관광공사에 따르면 2026년 6월 국민 해외관광객은 2,004,723명이다. 프리미엄 캐리어 비중이 커지고 있다.")
FIGURES = [
    {"metric": "market_size", "name": "국내 여행가방 시장 규모", "value": "2987", "unit": "krw", "period": "2025",
     "segment": "국내 여행가방", "quote": "국내 여행가방 시장 규모는 2025년 2987억원으로 집계됐다."},
    {"metric": "market_cagr", "name": "연평균 성장률", "value": "6.2", "unit": "percent", "period": "2026~2031",
     "segment": "국내 여행가방", "quote": "업계는 2026년부터 2031년까지 연평균 6.2% 성장할 것으로 본다."},
    {"metric": "macro_indicator", "name": "국민 해외관광객 수", "value": "2004723", "unit": "people", "period": "2026-06",
     "segment": "", "quote": "한국관광공사에 따르면 2026년 6월 국민 해외관광객은 2,004,723명이다."},
    {"metric": "market_size", "name": "지어낸 수치", "value": "5000", "unit": "krw", "period": "2025", "segment": "",
     "quote": "원문에 없는 문장이다."},
]


def test_market_item_turns_quoted_figures_into_candidate_facts(client, fakes):
    pid, plan = setup_project(client)
    market_it = item(plan, "market")
    seen_users = []

    def structured(system, user, schema, **kw):
        res = fakes.structured(system, user, schema, **kw)
        if "figures" in schema["properties"]:
            seen_users.append(user)
            data = dict(res.data, figures=FIGURES if "수치 추출: 사용" in user else [], facts=[], claims=[])
            return CallResult(data=data, usage=res.usage, cost_usd=res.cost_usd, cost_is_estimate=False)
        return res

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        return Page(url=url, final_url=url, title="여행가방 시장 동향", text=MARKET_PAGE, content_hash=url,
                    published="2026-07-01", publisher="예시뉴스", image_urls=[])

    research.PROVIDERS.update(structured=structured, fetch_page=fetch_page)
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [market_it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][market_it["id"]]
    assert res["status"] == "succeeded"
    card = next(m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["extraction_status"] == "pending")
    opened = ok(client.post(f"/v1/materials/{card['id']}/extract"))  # 사람이 자료를 열어 요약·추출
    assert len(opened["facts"]) == 3 and any("원문 인용 불일치" in d for d in opened["extraction"]["dropped"])
    assert seen_users and all("수치 추출: 사용" in u for u in seen_users)

    mats = [m for m in ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "market"}))
            if m["source"]["source_type"] != "social"]
    facts = {f["metric"]: f for f in mats[0]["facts"]}
    assert set(facts) == {"market_size", "market_cagr", "macro_indicator"}
    assert facts["market_size"]["value"] == "298700000000" and facts["market_size"]["unit"] == "krw"
    assert facts["market_cagr"]["period_start"] == "2026-01-01" and facts["market_cagr"]["period_end"] == "2031-12-31"
    assert facts["macro_indicator"]["dims"]["indicator"] == "국민 해외관광객 수"
    assert facts["macro_indicator"]["period_end"] == "2026-06-30"
    assert all(f["verification_status"] == "candidate" and f["dims"]["quote"] for f in facts.values())

    # accepting the material accepts its figures too
    ok(client.patch(f"/v1/materials/{mats[0]['id']}/review", json={"status": "accepted"}))
    after = ok(client.get(f"/v1/materials/{mats[0]['id']}"))
    assert all(f["verification_status"] == "eligible" for f in after["facts"] if f["metric"] in facts)


def test_campaign_items_do_not_extract_market_figures(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    users = []

    def structured(system, user, schema, **kw):
        if "figures" in schema["properties"]:
            users.append(user)
        return fakes.structured(system, user, schema, **kw)

    research.PROVIDERS.update(structured=structured)
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    open_pending(client, pid)  # 사람이 자료를 열어 요약·추출
    assert users and not any("수치 추출: 사용" in u for u in users)
