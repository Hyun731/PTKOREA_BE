"""P4-3 수동 항목 자동화: 이슈·포지셔닝·트렌드 항목을 웹 기사와 네이버 뉴스로 모아 자료 카드로."""
import pytest

from app.db import SessionLocal
from app.models import ProviderCache
from app.services import research, scope
from tests.integration.test_research import fakes, ok, setup_project  # noqa: F401 (fixture)


@pytest.fixture
def fresh_cache(client):
    """Cached answers must not leak into other modules' billing checks."""
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()


def test_manual_items_are_four_or_fewer():
    manual = [s["id"] for s in scope.ITEMS if s["collector"] is None]
    assert manual == ["2-1", "2-2", "2-3", "2-4"]  # 기업 개요·대표 약력·매출 구성·인지/NPS: 내부 자료(P4-5 업로드)
    for sid in ("4-1", "4-2", "4-3", "3-5", "3-6", "2-5", "6-1", "6-2"):
        spec = scope.BY_ID[sid]
        assert spec["collector"] == "issue" and scope.automation(spec, scope._default_channels(spec)) == "auto"
    assert scope.BY_ID["3-3"]["collector"] == "market" and scope.BY_ID["3-3"]["templates"] == ["M1"]


def test_risk_issue_item_collects_web_and_naver_news_cards(client, fakes, fresh_cache):
    pid, plan = setup_project(client)
    it = next(i for i in plan["items"] if i["scope_id"] == "4-2")
    assert it["section_id"] == "issue" and {c["id"] for c in it["channels"]} >= {"web", "naver_news"}
    fakes.search_name = it["entity"]  # the fake articles name the self brand
    fakes.naver_items = {"news": [
        {"title": f"{it['entity']} 품질 논란 해명", "url": "https://news.example.com/n1", "snippet": "해명",
         "date": "2026-08-01"},
        {"title": f"{it['entity']} 성수 팝업", "url": "https://news.example.com/a1", "snippet": "", "date": "2026-03-05"}]}
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    job = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert job["state"] == "succeeded", job
    res = job["result"]["items"][it["id"]]
    assert res["naver_news"] == 4  # two news queries × two fake items (the duplicate URL is kept once below)
    assert fakes.calls["naver_search"] == 2

    mats = ok(client.get(f"/v1/projects/{pid}/materials", params={"section_id": "issue"}))
    urls = {m["source"]["url"] for m in mats}
    assert "https://news.example.com/n1" in urls and "https://news.example.com/a1" in urls
    assert all(m["scope_id"] == "4-2" for m in mats), [(m["scope_id"], m["review_status"]) for m in mats]
    assert not any(m["review_status"] == "accepted" for m in mats)  # 자동 채택 없음 — 사람이 확인


def test_issue_queries_per_item(client):
    pid, plan = setup_project(client)
    from app.models import Project, ResearchItem
    with SessionLocal() as db:
        project = db.get(Project, pid)
        ids = {i["scope_id"]: i["id"] for i in plan["items"]}
        by_scope = {sid: db.get(ResearchItem, ids[sid]) for sid in ("4-1", "6-2", "3-3", "3-6")}
        q41 = research.build_queries(by_scope["4-1"], project)
        assert any("신제품 출시" in q for q in q41) and all(by_scope["4-1"].entity in q for q in q41)
        assert any("디지털 광고비 전망" in q for q in research.build_queries(by_scope["6-2"], project))
        assert any("신규 브랜드 진출" in q for q in research.build_queries(by_scope["3-3"], project))
        assert any("슬로건" in q for q in research.build_queries(by_scope["3-6"], project))
