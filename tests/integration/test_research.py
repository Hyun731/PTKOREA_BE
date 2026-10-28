"""Stage 2 with fake providers (no network): research runs, ledger/cache, budget, failures,
influencer collection and AI lead proposals (DEVELOPMENT_PLAN 단계 2 완료 조건; PRD A10, A14)."""
import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ProviderCache, ProviderCall
from app.services import insights, research
from integrations.base import CallResult, ProviderError
from integrations.fetch.page import Page

ARTICLE = ("경쟁X는 2026년 3월 성수동에서 팝업스토어를 열었다. 행사 기간 방문객은 12000명으로 집계됐다. "
           "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다.")


def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (800, 450), (20, 60, 120)).save(b, "PNG")
    return b.getvalue()


class Fakes:
    def __init__(self):
        self.calls: dict[str, int] = {}
        self.fail_search = None

    def _hit(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def search(self, queries, **kw):
        self._hit("search")
        if self.fail_search:
            raise ProviderError(self.fail_search, "fake failure", 403)
        return CallResult(data={"id": "s1", "results": [
            {"title": "경쟁X 성수 팝업", "url": "https://news.example.com/a1", "snippet": "팝업 소식", "date": "2026-03-05"},
            {"title": "경쟁X 영상", "url": "https://www.youtube.com/watch?v=abc", "snippet": "영상", "date": None},
        ]}, cost_usd=0.005)

    def fetch_page(self, url, **kw):
        self._hit("fetch_page")
        return Page(url=url, final_url=url, title="경쟁X, 성수 팝업 열어", text=ARTICLE, content_hash="h1",
                    published="2026-03-05", publisher="예시뉴스", image_urls=["https://news.example.com/og.png"])

    def fetch_image(self, url, **kw):
        self._hit("fetch_image")
        return png()

    def structured(self, system, user, schema, **kw):
        self._hit("structured")
        if "facts" in schema["properties"]:  # extraction
            return CallResult(data={
                "relevant": True, "relevance_note": "", "activity_date": "2026-03-01",
                "facts": [{"label": "방문객", "metric": "count", "value": "12000", "quote": "행사 기간 방문객은 12000명으로 집계됐다."},
                          {"label": "가짜", "metric": "count", "value": "999", "quote": "원문에 없는 문장."}],
                "claims": [{"kind": "fact", "text": "성수동 팝업에 신제품 체험 공간 배치", "quote": "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다."},
                           {"kind": "interpretation", "text": "방문객 {{1}} 규모의 체험형 접점", "quote": "행사 기간 방문객은 12000명으로 집계됐다."},
                           {"kind": "fact", "text": "3월 팝업 개최", "quote": "경쟁X는 2026년 3월 성수동에서 팝업스토어를 열었다."}],
            }, usage={"input_tokens": 1000, "output_tokens": 200, "model": "fake"}, cost_usd=0.008, cost_is_estimate=False)
        # lead: first answer breaks the digit rule, the rewrite is valid
        n = self.calls["structured"]
        if "이전 답의 문제" not in user:
            segs = [{"text": "검색 점유 12M 기준 우위 축소", "fact_ref": None, "bold": False}]
        else:
            segs = [{"text": "브랜드 검색 점유 우위 축소", "fact_ref": None, "bold": True}, {"text": " — 격차 ", "fact_ref": None, "bold": False},
                    {"text": "", "fact_ref": 1, "bold": True}]
        return CallResult(data={"segments": segs}, usage={"input_tokens": 500, "output_tokens": 50, "model": "fake"},
                          cost_usd=0.003 + n * 0, cost_is_estimate=False)

    def instagram_post(self, url, **kw):
        self._hit("instagram_post")
        return CallResult(data={"platform": "instagram", "url": url, "post_id": "C1x", "posted_at": "2026-05-02", "title": "",
                                "creator": "ig_creator", "followers": None, "views": None, "likes": None, "comments": 120,
                                "likes_hidden": True, "image_urls": [], "paid_promotion": None}, cost_usd=0.002)

    def instagram_profile(self, handle, **kw):
        self._hit("instagram_profile")
        return CallResult(data={"followers": 80000, "name": handle}, cost_usd=0.002)

    def youtube_video(self, url, **kw):
        self._hit("youtube_video")
        return CallResult(data={"platform": "youtube", "url": url, "post_id": "vid1", "posted_at": "2026-06-10", "title": "리뷰",
                                "creator": "유튜버", "channel_url": "https://www.youtube.com/@yt", "followers": None,
                                "views": 300000, "likes": 6000, "comments": 400, "likes_hidden": False,
                                "image_urls": [], "paid_promotion": True}, cost_usd=0.002)

    def youtube_channel(self, url=None, **kw):
        self._hit("youtube_channel")
        return CallResult(data={"subscribers": 200000, "name": "유튜버"}, cost_usd=0.002)

    def search_trend(self, groups, start, end, **kw):
        self._hit("search_trend")
        # One ratio per month in [start, end], distinct per group so shares aren't tied.
        months = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.append(f"{y:04d}-{m:02d}-01")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        base = {name: 20 + 10 * i for i, (name, _) in enumerate(groups)}
        return CallResult(data={"results": [
            {"group": name, "points": [{"period": period, "ratio": float(base[name] + i)} for i, period in enumerate(months)]}
            for name, _ in groups
        ]}, usage={"requests": 1}, cost_usd=0.0, cost_is_estimate=False)


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    research.PROVIDERS.clear()
    research.PROVIDERS.update(search=f.search, fetch_page=f.fetch_page, fetch_image=f.fetch_image, structured=f.structured,
                              instagram_post=f.instagram_post, instagram_profile=f.instagram_profile, youtube_video=f.youtube_video,
                              youtube_channel=f.youtube_channel, naver_search_trend=f.search_trend)
    insights.STRUCTURED.clear()
    insights.STRUCTURED.append(f.structured)
    for k in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "fake-model")
    monkeypatch.setenv("RUN_BUDGET_USD", "5")
    yield f
    research.PROVIDERS.clear()
    insights.STRUCTURED.clear()


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def setup_project(client):
    p = ok(client.post("/v1/projects/sample"), 201)
    plan = ok(client.get(f"/v1/projects/{p['id']}/research-plan"))
    return p["id"], plan


def item(plan, section, entity=None):
    return next(i for i in plan["items"] if i["section_id"] == section and (entity is None or i["entity"] == entity))


def ledger_rows(pid):
    with SessionLocal() as db:
        return list(db.scalars(select(ProviderCall).where(ProviderCall.project_id == pid)))


def test_campaign_run_creates_candidates_without_rebilling(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    job = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert job["state"] == "succeeded", job
    res = job["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["created"] == 2 and res["pages"] == 1 and res["images"] == 1
    assert res["facts"] == 1 and res["claims"] == 2  # fake quote and bare-digit claim are dropped
    assert any("원문 인용 불일치" in d for d in res["dropped"]) and any("근거 없는 숫자" in d for d in res["dropped"])

    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    article = next(m for m in mats if m["source"]["url"] == "https://news.example.com/a1")
    assert article["input_path"] == "auto" and article["review_status"] == "candidate"
    assert article["source"]["publisher"] == "예시뉴스" and article["source"]["published_at"] == "2026-03-05"
    assert article["assets"][0]["review_status"] == "candidate" and article["assets"][0]["usage_basis"] == "source_reference"
    ai = [c for c in article["claims"] if c["author"] == "ai"]
    assert all(c["review_status"] == "pending" and c["quote"] for c in ai)
    interp = next(c for c in ai if c["kind"] == "interpretation")
    assert "12,000" in interp["text"] and interp["fact_ids"]  # number bound to an extracted fact
    assert article["facts"][0]["verification_status"] == "candidate" and article["facts"][0]["origin"] == "auto"
    social = next(m for m in mats if "youtube" in (m["source"]["url"] or ""))
    assert social["source"]["source_type"] == "social" and social["assets"] == []

    paid = [r for r in ledger_rows(pid) if r.status == "settled"]
    assert {r.provider for r in paid} == {"perplexity", "anthropic"}
    assert ok(client.get(f"/v1/projects/{pid}/usage"))["total_cost_usd"] > 0

    # Re-run without force: the succeeded item is skipped, no provider is called.
    before = dict(fakes.calls)
    job2 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job2['id']}"))["result"]["items"][it["id"]]["status"] == "skipped"
    assert fakes.calls == before
    # Forced re-run hits the response cache: no new paid search, existing URLs are not duplicated.
    job3 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]], "force": True}), 202)["job"]
    r3 = ok(client.get(f"/v1/jobs/{job3['id']}"))["result"]["items"][it["id"]]
    assert fakes.calls["search"] == before["search"]
    assert r3["skipped_existing"] == 2 and len(ok(client.get(f"/v1/projects/{pid}/materials"))) == len(mats)
    assert any(r.status == "cache_hit" and r.job_id == job3["id"] for r in ledger_rows(pid))


def test_budget_and_provider_failure_keep_existing_material(client, fakes, monkeypatch):
    pid, plan = setup_project(client)
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "기존 수동 자료", "section_id": "campaign"}), 201)
    it = item(plan, "campaign", "경쟁Y")
    monkeypatch.setenv("RUN_BUDGET_USD", "0.001")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "blocked_budget" and fakes.calls.get("search", 0) == 0

    monkeypatch.setenv("RUN_BUDGET_USD", "5")
    fakes.fail_search = "PROVIDER_AUTH"
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res["errors"][0]["code"] == "PROVIDER_AUTH"
    assert [x["id"] for x in ok(client.get(f"/v1/projects/{pid}/materials"))] == [m["id"]]  # nothing deleted
    plan2 = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    assert item(plan2, "campaign", "경쟁Y")["execution_status"] == "failed"


def test_influencer_urls_become_candidate_batch(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    bad = client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://example.com/x"]})
    assert bad.status_code == 422
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": [
        "https://www.instagram.com/p/C1x/", "https://www.youtube.com/watch?v=vid1"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["posts"] == 2
    batch = next(b for b in ok(client.get(f"/v1/projects/{pid}/imports")) if b["id"] == res["batch_id"])
    assert batch["status"] == "candidate" and batch["kind"] == "posts" and not batch["synthetic"]
    assert fakes.calls["youtube_channel"] == 1  # subscribers come from the channel endpoint
    assert fakes.calls["instagram_profile"] == 1  # Instagram followers come from the profile endpoint
    ok(client.post(f"/v1/imports/{batch['id']}/review", json={"action": "accept"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "3-1-B1")["readiness"] == "ready"


def test_search_items_auto_collect_via_naver(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "search")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["facts"] > 0
    assert fakes.calls["search_trend"] == 1  # one DataLab call covers 12M and 9M alike (same scale_id)

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    assert facts and all(f["verification_status"] == "candidate" and f["origin"] == "auto" for f in facts)
    windows = {f["dims"]["window"] for f in facts if f["metric"] == "search_group_sum"}
    assert windows == {"12M", "9M"}
    for f in facts:
        ok(client.patch(f"/v1/facts/{f['id']}/review?project_id={pid}", json={"action": "confirm"}))

    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-8a")["readiness"] == "ready"
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-8b")["readiness"] == "ready"


def test_search_items_need_naver_key(client, fakes, monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    pid, plan = setup_project(client)
    it = item(plan, "search")
    r = client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]})
    assert r.status_code == 503
    assert r.json()["error"]["detail"]["providers"] == ["naver"]


def test_lead_proposal_rewrite_then_accept(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    job = ok(client.post(f"/v1/projects/{pid}/insight-proposals", json={"slide_ids": ["2-8a"]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    props = ok(client.get(f"/v1/projects/{pid}/insight-proposals"))
    lp = next(p for p in props if p["slide_id"] == "2-8a")
    assert lp["status"] == "pending" and lp["attempts"] == 2  # first answer had a bare number
    assert any(p["type"] == "fact" for p in lp["parts"])
    ok(client.post(f"/v1/insight-proposals/{lp['id']}/review", json={"action": "accept"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert not [i for i in sp["qc"]["issues"] if i["slide_id"] == "2-8a" and i["severity"] == "block"]
    # The rule lead comes back when the override is cleared.
    ok(client.delete(f"/v1/projects/{pid}/lead-overrides/2-8a"))


def test_same_activity_from_two_outlets_becomes_one_card(client, fakes):
    """Two articles about one campaign (same press image) -> one card plus an extra source, no second AI call."""
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")

    def search(queries, **kw):
        fakes._hit("search")
        return CallResult(data={"id": "s2", "results": [
            {"title": "경쟁X, 일러스트레이터 키크니와 협업 이벤트 진행", "url": "https://a.example.com/1", "snippet": "", "date": "2026-02-07"},
            {"title": "경쟁X, 인기 작가 키크니와 직장인 공감 캠페인 전개 - TENANT news", "url": "https://b.example.com/2", "snippet": "", "date": "2026-02-04"},
        ]}, cost_usd=0.005)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        title = "경쟁X, 일러스트레이터 키크니와 협업 이벤트 진행" if "a.example" in url else "경쟁X, 인기 작가 키크니와 직장인 공감 캠페인 전개"
        return Page(url=url, final_url=url, title=title, text=ARTICLE, content_hash=url, published=None, publisher=None,
                    image_urls=["https://img.example.com/press.png"])

    research.PROVIDERS.update(search=search, fetch_page=fetch_page)
    with SessionLocal() as db:  # other tests cached the same search request
        db.query(ProviderCache).delete()
        db.commit()
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["created"] == 2 and res["duplicates"] == 1
    assert fakes.calls["structured"] == 1  # the duplicate skipped AI extraction

    mats = ok(client.get(f"/v1/projects/{pid}/materials"))
    primary = next(m for m in mats if m["source"]["url"] == "https://a.example.com/1")
    extra = next(m for m in mats if m["source"]["url"] == "https://b.example.com/2")
    assert primary["duplicate_of"] is None and [d["id"] for d in primary["duplicates"]] == [extra["id"]]
    assert extra["duplicate_of"] == primary["id"] and extra["duplicate_reason"] == "같은 대표 이미지"
    assert ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"][it["order"] - 1]["coverage"]["duplicates"] == 1

    # An extra source cannot be accepted on its own.
    r = client.patch(f"/v1/materials/{extra['id']}/review", json={"status": "accepted"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IS_DUPLICATE"

    # Swap the primary: the acceptance moves with it.
    ok(client.patch(f"/v1/materials/{primary['id']}/review", json={"status": "accepted"}))
    swapped = ok(client.post(f"/v1/materials/{extra['id']}/duplicate", json={"make_primary": True}))
    assert swapped["duplicate_of"] is None and swapped["review_status"] == "accepted"
    old = ok(client.get(f"/v1/materials/{primary['id']}"))
    assert old["duplicate_of"] == extra["id"] and old["review_status"] == "candidate"

    # Split it off: a later scan does not merge it back.
    ok(client.post(f"/v1/materials/{primary['id']}/duplicate", json={"of": None}))
    assert ok(client.post(f"/v1/projects/{pid}/materials/dedupe"))["merged"] == []
    assert ok(client.get(f"/v1/materials/{primary['id']}"))["duplicate_of"] is None

    # Merge by hand.
    merged = ok(client.post(f"/v1/materials/{primary['id']}/duplicate", json={"of": extra["id"]}))
    assert merged["duplicate_of"] == extra["id"]


def test_dedupe_scan_groups_existing_manual_cards(client, fakes):
    pid, _ = setup_project(client)
    body = {"section_id": "campaign", "entity": "경쟁X", "brand_id": "B1"}
    a = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X 넥시스 팝업 성수 오픈", "activity_date": "2026-07-10"}), 201)
    b = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X, 성수서 넥시스 체험 팝업", "activity_date": "2026-07-12"}), 201)
    c = ok(client.post(f"/v1/projects/{pid}/materials", json={**body, "title": "경쟁X 여름 할인 프로모션", "activity_date": "2026-07-11"}), 201)
    merged = ok(client.post(f"/v1/projects/{pid}/materials/dedupe"))["merged"]
    assert [(x["id"], x["primary_id"]) for x in merged] == [(b["id"], a["id"])]
    assert ok(client.get(f"/v1/materials/{c['id']}"))["duplicate_of"] is None


def test_patch_material_with_dates_is_audited(client, fakes):
    pid, _ = setup_project(client)
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "날짜 있는 자료", "activity_date": "2026-03-01",
                                                               "published_at": "2026-03-02", "url": "https://e.com/a"}), 201)
    m2 = ok(client.patch(f"/v1/materials/{m['id']}", json={"base_version": m["version"], "title": "새 제목"}))
    assert m2["title"] == "새 제목"


def test_runs_overlap_unless_they_share_an_item(client, fakes):
    """Two research runs can be in flight together; the same item cannot be researched twice at once."""
    from app.models import Job
    pid, plan = setup_project(client)
    a, b = item(plan, "campaign", "경쟁X"), item(plan, "campaign", "경쟁Y")
    with SessionLocal() as db:  # a run that is still going for item a
        db.add(Job(id="JOB-busy", project_id=pid, kind="research_run", state="running", params={"item_ids": [a["id"]]},
                   project_version=1))
        db.commit()
    try:
        r = client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [a["id"]]})
        assert r.status_code == 409 and r.json()["error"]["detail"]["item_ids"] == [a["id"]]
        job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [b["id"]]}), 202)["job"]
        assert ok(client.get(f"/v1/jobs/{job['id']}"))["state"] == "succeeded"
    finally:
        with SessionLocal() as db:
            db.get(Job, "JOB-busy").state = "cancelled"
            db.commit()


def test_items_of_one_run_are_researched_in_parallel(client, fakes, monkeypatch):
    import threading
    import time
    pid, plan = setup_project(client)
    ids = [item(plan, "campaign", e)["id"] for e in ("경쟁X", "경쟁Y")]
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    active, peak, lock = [0], [0], threading.Lock()
    original = fakes.search

    def slow_search(queries, **kw):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.3)
        with lock:
            active[0] -= 1
        res = original(queries, **kw)
        tag = "x" if "경쟁X" in queries[0] else "y"  # each item finds its own articles
        res.data = {**res.data, "results": [{**r, "url": r["url"] + f"?{tag}"} for r in res.data["results"]]}
        return res

    research.PROVIDERS["search"] = slow_search
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": ids}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert res["state"] == "succeeded" and all(res["result"]["items"][i]["status"] in ("succeeded", "partial") for i in ids)
    assert peak[0] >= 2  # both items were searching at the same time


def test_interrupted_run_releases_its_items(client, fakes):
    """A run killed by a server restart must not leave its items locked as 'running'."""
    from app.jobs import recover_orphans
    from app.models import Job, ResearchItem
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:
        db.add(Job(id="JOB-dead", project_id=pid, kind="research_run", state="running", params={"item_ids": [it["id"]]},
                   project_version=1))
        row = db.get(ResearchItem, it["id"])
        row.execution_status, row.latest_job_id = "running", "JOB-dead"
        db.commit()
    recover_orphans()
    after = next(i for i in ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"] if i["id"] == it["id"])
    assert after["execution_status"] == "failed" and after["last_result"]["errors"][0]["code"] == "WORKER_RESTARTED"


def test_plan_regeneration_keeps_item_inputs(client, fakes):
    """Saving project settings regenerates the plan; the post URLs a person entered must survive."""
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://www.youtube.com/watch?v=vid1"]}))
    project = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": project["version"],
                                                "changes": {"enabled_slides": project["config"]["enabled_slides"] + ["M1"]}}))
    again = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "influencer")
    assert again["id"] != it["id"] and again["inputs"]["post_urls"] == ["https://www.youtube.com/watch?v=vid1"]


def test_research_keeps_to_the_period(client, fakes):
    """Search carries a publish-date window; far-off results are not fetched; an activity outside the
    period is excluded with a reason; the period check re-applies the rule to existing cards."""
    from datetime import date, timedelta

    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    start, end = date.fromisoformat(it["period_start"]), date.fromisoformat(it["period_end"])
    seen = {}

    def search(queries, **kw):
        fakes._hit("search")
        seen.setdefault("calls", []).append(kw)
        return CallResult(data={"id": "s3", "results": [
            {"title": "경쟁X 기간 안 팝업", "url": "https://p.example.com/in", "snippet": "", "date": str(start + timedelta(days=20))},
            {"title": "경쟁X 오래된 기사", "url": "https://p.example.com/old", "snippet": "", "date": str(start - timedelta(days=400))},
            {"title": "지난해 겨울 한정판 회고 인터뷰", "url": "https://q.example.org/past", "snippet": "", "date": str(start + timedelta(days=90))},
        ]}, cost_usd=0.005)

    def structured(system, user, schema, **kw):
        if "facts" not in schema["properties"]:
            return fakes.structured(system, user, schema, **kw)
        fakes._hit("structured")
        past = "q.example.org/past" in user
        act = start - timedelta(days=200) if past else start + timedelta(days=15)
        return CallResult(data={"relevant": not past, "relevance_note": "작년 활동" if past else "", "activity_date": str(act),
                                "activity_date_end": None, "event_name": "팝업", "same_as": None, "facts": [], "claims": []},
                          usage={"input_tokens": 10, "output_tokens": 10, "model": "fake"}, cost_usd=0.001, cost_is_estimate=False)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        return Page(url=url, final_url=url, title=url, text=ARTICLE, content_hash=url, published=None, publisher=None, image_urls=[])

    research.PROVIDERS.update(search=search, structured=structured, fetch_page=fetch_page)
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    calls = seen["calls"]  # the period is searched in parts that together span lead..tail
    assert len(calls) == 3
    assert calls[0]["published_after"] == (start - timedelta(days=30)).strftime("%m/%d/%Y")
    assert calls[-1]["published_before"] == (end + timedelta(days=14)).strftime("%m/%d/%Y")
    assert res["created"] == 2 and res["out_of_period"] == 2  # one never fetched, one excluded after extraction

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials"))}
    assert "https://p.example.com/old" not in mats
    assert mats["https://p.example.com/in"]["review_status"] == "candidate"
    past = mats["https://q.example.org/past"]
    assert past["review_status"] == "excluded" and past["review_reason"].startswith("조사 기간 밖")

    # Correcting the date and re-checking brings it back; the rule never touches reviewed cards.
    ok(client.patch(f"/v1/materials/{past['id']}", json={"base_version": past["version"], "activity_date": str(start + timedelta(days=5))}))
    out = ok(client.post(f"/v1/projects/{pid}/materials/period-check"))
    assert out["checked"] >= 2 and out["excluded"] == []
    assert ok(client.get(f"/v1/materials/{past['id']}"))["review_status"] == "candidate"


def test_hashtag_discovery_adds_in_period_creator_posts(client, fakes, monkeypatch):
    """Apify finds posts by hashtag; only in-period, non-official posts are added, best engagement first,
    and their metrics are then collected like hand-picked URLs."""
    from datetime import date, timedelta

    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    pid, plan = setup_project(client)
    it = item(plan, "influencer")
    start = date.fromisoformat(it["period_start"])
    day = str(start + timedelta(days=30))

    def hashtag(tags, per_tag=60, **kw):
        fakes._hit("instagram_hashtag")
        posts = [
            {"url": "https://www.instagram.com/p/AAA/", "posted_at": day, "creator": "runner_kim", "likes": 900, "comments": 40, "views": None},
            {"url": "https://www.instagram.com/p/BBB/", "posted_at": day, "creator": "small_fit", "likes": 30, "comments": 2, "views": None},
            {"url": "https://www.instagram.com/p/CCC/", "posted_at": day, "creator": "brand1_official", "likes": 5000, "comments": 300, "views": None},
            {"url": "https://www.instagram.com/p/DDD/", "posted_at": str(start - timedelta(days=90)), "creator": "old_post", "likes": 9000, "comments": 900, "views": None},
        ]
        return CallResult(data={"posts": posts}, usage={"results": len(posts)}, cost_usd=0.01)

    research.PROVIDERS["instagram_hashtag"] = hashtag
    # brand B1's latin alias marks its own accounts
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["aliases"] = ["Brand1"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": [], "hashtags": ["#브랜드1", "brand1"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    d = res["discovered"]
    assert d["found"] == 4 and d["official"] == 1 and d["out_of_period"] == 1 and d["added"] == 2
    saved = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    urls = item(saved, "influencer")["inputs"]["post_urls"]
    assert urls == ["https://www.instagram.com/p/AAA/", "https://www.instagram.com/p/BBB/"]  # best engagement first
    assert fakes.calls["instagram_post"] >= 2 and res["posts"] >= 1  # the fake returns one post id for every URL
