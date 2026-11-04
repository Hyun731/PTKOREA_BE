"""Stage 2 with fake providers (no network): research runs, ledger/cache, budget, failures,
influencer collection and AI lead proposals (DEVELOPMENT_PLAN 단계 2 완료 조건; PRD A10, A14)."""
import io
import re

import pytest
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import FactRow, Material, PostRow, ProviderCache, ProviderCall, Source, new_id, utcnow
from app.services import (
    aliases, case_commentary, direction, industry, insights, material_ai, official_accounts, outline, research,
    synthesis,
)
from integrations.base import CallResult, ProviderError
from integrations.fetch.page import Page

ARTICLE = ("경쟁X는 2026년 3월 성수동에서 팝업스토어를 열었다. 행사 기간 방문객은 12000명으로 집계됐다. "
           "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다.")


def png(color: tuple[int, int, int] = (20, 60, 120)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (800, 450), color).save(b, "PNG")
    return b.getvalue()


class Fakes:
    def __init__(self):
        self.calls: dict[str, int] = {}
        self.fail_search = None
        self.search_name = "경쟁X"  # how the fake articles name the brand

    def _hit(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def search(self, queries, **kw):
        self._hit("search")
        if self.fail_search:
            raise ProviderError(self.fail_search, "fake failure", 403)
        return CallResult(data={"id": "s1", "results": [
            {"title": f"{self.search_name} 성수 팝업", "url": "https://news.example.com/a1", "snippet": "팝업 소식", "date": "2026-03-05"},
            {"title": f"{self.search_name} 영상", "url": "https://www.youtube.com/watch?v=abc", "snippet": "영상", "date": None},
        ]}, cost_usd=0.005)

    def fetch_page(self, url, **kw):
        self._hit("fetch_page")
        return Page(url=url, final_url=url, title="경쟁X, 성수 팝업 열어", text=ARTICLE, content_hash="h1",
                    published="2026-03-05", publisher="예시뉴스", image_urls=["https://news.example.com/og.png"])

    def fetch_image(self, url, **kw):
        self._hit("fetch_image")
        # Distinct per URL — a real photo per post, not the same bytes (and sha256) every time.
        return png((abs(hash(url)) % 200, abs(hash(url[::-1])) % 200, 80))

    def structured(self, system, user, schema, **kw):
        props = schema["properties"]
        if set(props) == {"brands"}:
            item_props = set(schema["properties"]["brands"]["items"]["properties"])
            if item_props == {"name", "industry"}:  # 업종 추천: echo back whichever brand name was asked about
                self._hit("industry")
                names = user.split("<brands>\n")[-1].split("\n</brands>")[0].splitlines()
                return CallResult(data={"brands": [{"name": n, "industry": "패션"} for n in names]},
                                  usage={"model": "fake"}, cost_usd=0.001)
            self._hit("aliases")  # 다른 표기: only the competitor has a known English name
            return CallResult(data={"brands": [{"name": "경쟁X", "aliases": ["CompetitorX", "경쟁X"]}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"profiles"}:  # 공식 계정 후보
            self._hit("official_accounts")
            return CallResult(data={"profiles": [
                {"channel": "instagram", "url": "https://instagram.com/competitorx_official", "confident": True}]},
                              usage={"model": "fake"}, cost_usd=0.001)
        self._hit("structured")
        if "es_company" in props or "swot_lead" in props or "problem_lead" in props:  # 종합 장표(고른 유형만)
            data: dict = {}
            if "es_company" in props:  # one line has a number and one points at a page that doesn't exist
                ref = re.search(r'"id": "([^"]+)"', user).group(1)
                data.update({
                    "es_company": [{"text": "크리에이터 게시물 중심의 자사 관측", "ref": ref}],
                    "es_competitor": [{"text": "경쟁 세트 안 검색 점유 우위 축소", "ref": "2-8a"},
                                      {"text": "점유 12퍼센트 하락", "ref": "2-8a"}, {"text": "없는 장 근거", "ref": "Z-9"}],
                    "es_customer": [], "task": "검색 점유 방어를 위한 접점 확대 필요",
                    "insights": [{"title": "검색 우위 축소", "body": "경쟁 세트 안에서 검색 점유가 줄어드는 흐름"}]})
            if "swot_lead" in props:
                data.update({"swot_lead": "자사 접점은 넓고 검색 점유는 낮은 편", "S": ["크리에이터 협업 접점"],
                            "W": ["검색 점유 우위 축소"], "O": ["카테고리 조합어 검색 수요"], "T": ["경쟁사 검색 점유 상승"]})
            if "problem_lead" in props:
                data.update({"problem_lead": "검색 접점에서 경쟁 열위", "problems": ["검색 노출 열세", "콘텐츠 반응 둔화"],
                            "solutions": [{"title": "검색 접점 확대", "body": "크리에이터 콘텐츠에 브랜드명 검색 유도 문구 배치"}]})
            return CallResult(data=data, usage={"model": "fake"}, cost_usd=0.01)
        if "action" in props:  # 초안 흐름 장표 피드백
            fb = user.split("<feedback>")[-1]
            if "빼" in fb:
                return CallResult(data={"reply": "이 장을 뺐습니다.", "action": "omit", "segments": []}, usage={"model": "fake"}, cost_usd=0.002)
            if "순서" in fb:
                return CallResult(data={"reply": "장 순서는 이 단계에서 바꿀 수 없습니다.", "action": "none", "segments": []},
                                  usage={"model": "fake"}, cost_usd=0.002)
            seg = [{"text": "브랜드 검색 점유 12% 우위 축소", "fact_ref": None, "bold": True}] if "깨기" in fb else \
                  [{"text": "브랜드 검색 점유 우위가 줄어든 흐름", "fact_ref": None, "bold": True}]
            return CallResult(data={"reply": "리드를 다시 썼습니다.", "action": "rewrite_lead", "segments": seg},
                              usage={"model": "fake"}, cost_usd=0.002)
        if "suggestions" in props:  # 문장 추천: one verbatim quote, one made-up quote, one with a bare number
            return CallResult(data={"suggestions": [
                {"kind": "fact", "text": "성수동 팝업에 신제품 체험 공간 배치", "quote": "브랜드는 신제품 캐리어를 체험 공간에 배치하고 현장 구매 혜택을 제공했다."},
                {"kind": "interpretation", "text": "원문에 없는 관찰", "quote": "원문에 없는 문장."},
                {"kind": "fact", "text": "방문객 12000명 집계", "quote": "행사 기간 방문객은 12000명으로 집계됐다."}]},
                usage={"model": "fake"}, cost_usd=0.002)
        if set(props) == {"text"}:  # 다듬기: keeps the fact token unless asked to break it
            keep = re.search(r"\{\{[^}]+\}\}", user)
            return CallResult(data={"text": ("조회 " + keep.group(0) + " 규모의 체험형 확산 확인") if keep and "깨기" not in user
                                    else "체험형 팝업으로 화제성 확보 99"}, usage={"model": "fake"}, cost_usd=0.001)
        if set(props) == {"summary"}:
            return CallResult(data={"summary": "직접 만든 카드의 요약입니다."}, usage={"model": "fake"}, cost_usd=0.001)
        if "search_query" in props:  # 자료 대화: asks for a search first, answers from it after
            if "<search>" not in user:
                return CallResult(data={"answer": "원문에서 확인되지 않습니다", "search_query": "경쟁X 팝업 방문객", "used": []},
                                  usage={"model": "fake"}, cost_usd=0.002)
            return CallResult(data={"answer": "추가 기사에 따르면 주말 방문이 많았습니다.", "search_query": None, "used": [1, 9]},
                              usage={"model": "fake"}, cost_usd=0.002)
        if "keywords" in props:  # 조사 방향 대화
            return CallResult(data={
                "reply": "기간을 최근 12개월로 바꾸고 팝업 사례를 먼저 보게 했습니다.", "enabled": True, "period": "months",
                "months": 12, "start": None, "end": None, "channels": ["web", "instagram", "없는채널"],
                "targets": ["경쟁X"], "max_items": 4, "focus": "팝업·오프라인 행사 사례를 먼저 봅니다.",
                "keywords": ["팝업스토어"]}, usage={"input_tokens": 300, "output_tokens": 80, "model": "fake"}, cost_usd=0.002)
        if "detail" in schema["properties"]:  # P4 case commentary
            if "이전 답의 문제" not in user:
                return CallResult(data={"detail": "3일 만에 완판된 협업 캡슐 컬렉션", "implication": "자사도 한정판 캡슐로 화제성 확보"},
                                  usage={"input_tokens": 100, "output_tokens": 30, "model": "fake"}, cost_usd=0.001)
            return CallResult(data={"detail": "짧은 기간에 완판된 협업 캡슐 컬렉션", "implication": "자사도 한정판 캡슐로 화제성 확보"},
                              usage={"input_tokens": 100, "output_tokens": 30, "model": "fake"}, cost_usd=0.001)
        if "facts" in schema["properties"]:  # extraction
            return CallResult(data={
                "relevant": True, "relevance_note": "", "activity_date": "2026-03-01",
                "summary": "성수동 팝업에서 신제품 체험 공간을 열어 방문객을 모은 활동입니다.",
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

    def instagram_user_posts(self, handle, next_max_id=None, **kw):
        self._hit("instagram_user_posts")
        if next_max_id:
            return CallResult(data={"posts": [], "next_max_id": None, "more_available": False}, cost_usd=0.002)
        posts = [
            {"post_id": "p1", "posted_at": "2026-08-05", "likes": 500, "comments": 10, "views": None,
             "url": "https://instagram.com/p/p1/", "image_url": "https://img.example.com/p1.jpg"},
            {"post_id": "p2", "posted_at": "2026-09-10", "likes": 900, "comments": 20, "views": None,
             "url": "https://instagram.com/p/p2/", "image_url": "https://img.example.com/p2.jpg"},
            {"post_id": "p3", "posted_at": "2026-09-20", "likes": 100, "comments": 5, "views": None,
             "url": "https://instagram.com/p/p3/", "image_url": None},
        ]
        return CallResult(data={"posts": posts, "next_max_id": None, "more_available": False}, cost_usd=0.002)

    def youtube_channel_videos(self, channel_id=None, handle=None, continuation_token=None, **kw):
        self._hit("youtube_channel_videos")
        videos = [{"id": "v1", "url": "https://youtube.com/watch?v=v1", "title": "영상1", "views": 1000,
                  "published_at": "2026-09-01", "length_seconds": 120, "is_short": False}]
        return CallResult(data={"videos": videos, "continuation_token": None}, cost_usd=0.002)

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
                              youtube_channel=f.youtube_channel, naver_search_trend=f.search_trend,
                              instagram_user_posts=f.instagram_user_posts, youtube_channel_videos=f.youtube_channel_videos)
    aliases.STRUCTURED.clear()
    aliases.STRUCTURED.append(f.structured)
    industry.STRUCTURED.clear()
    industry.STRUCTURED.append(f.structured)
    official_accounts.STRUCTURED.clear()
    official_accounts.STRUCTURED.append(f.structured)
    official_accounts.SEARCH.clear()
    official_accounts.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    insights.STRUCTURED.clear()
    insights.STRUCTURED.append(f.structured)
    case_commentary.STRUCTURED.clear()
    case_commentary.STRUCTURED.append(f.structured)
    direction.STRUCTURED.clear()
    direction.STRUCTURED.append(f.structured)
    material_ai.STRUCTURED.clear()
    material_ai.STRUCTURED.append(f.structured)
    material_ai.SEARCH.clear()
    material_ai.SEARCH.append(lambda qs, **kw: f.search(qs, **kw))
    outline.STRUCTURED.clear()
    outline.STRUCTURED.append(f.structured)
    synthesis.STRUCTURED.clear()
    synthesis.STRUCTURED.append(f.structured)
    for k in ("PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "fake-model")
    monkeypatch.setenv("RUN_BUDGET_USD", "5")
    yield f
    research.PROVIDERS.clear()
    aliases.STRUCTURED.clear()
    industry.STRUCTURED.clear()
    official_accounts.STRUCTURED.clear()
    official_accounts.SEARCH.clear()
    insights.STRUCTURED.clear()
    case_commentary.STRUCTURED.clear()
    direction.STRUCTURED.clear()
    material_ai.STRUCTURED.clear()
    material_ai.SEARCH.clear()
    outline.STRUCTURED.clear()
    synthesis.STRUCTURED.clear()


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def setup_project(client):
    p = ok(client.post("/v1/projects/sample"), 201)
    plan = ok(client.get(f"/v1/projects/{p['id']}/research-plan"))
    return p["id"], plan


def item(plan, section, entity=None):
    return next(i for i in plan["items"] if i["section_id"] == section and (entity is None or i["entity"] == entity))


def clear_cache():
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()


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
    assert article["input_path"] == "auto" and article["review_status"] == "candidate"  # a person reviews every card
    assert article["scope_id"] == "3-7" and article["role"] == "competitor"  # its place in the 3C plan
    assert article["summary"].startswith("성수동 팝업")  # 해석 요약 comes with the extraction, no extra call
    with SessionLocal() as db:
        assert "방문객" in (db.get(Source, article["source"]["id"]).text or "")  # page text kept for later AI help
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


def test_influencer_urls_become_candidate_batch(client, fakes, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate manual-URL handling from YouTube auto-discovery
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


def test_influencer_item_finds_posts_without_any_input(client, fakes, monkeypatch):
    """Phase 1-2: no post_urls, no hashtags — the brand name becomes the Instagram hashtag and the
    YouTube search term, Owned/Earned is split by official handle, and YouTube's native paid-promotion
    flag marks the sponsored post."""
    monkeypatch.setenv("APIFY_TOKEN", "test-token")

    def hashtag(tags, per_tag=60, **kw):
        fakes._hit("instagram_hashtag")
        assert tags == ["브랜드A", "브랜드 A"]  # 브랜드 이름 + 다른 표기로 자동 생성됨
        return CallResult(data={"posts": [
            {"url": "https://www.instagram.com/p/EARNED1/", "posted_at": "2026-08-10", "creator": "fit_runner",
             "likes": 400, "comments": 10, "views": None}]}, usage={"results": 1}, cost_usd=0.01)

    research.PROVIDERS["instagram_hashtag"] = hashtag
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "influencer")
    assert (it["inputs"] or {}).get("post_urls") in (None, []) and (it["inputs"] or {}).get("hashtags") in (None, [])
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["posts"] == 2  # IG 해시태그 1건 + YouTube 검색 1건
    assert res["coverage_short"] is True  # 목표 10건에 한참 못 미침

    batch = next(b for b in ok(client.get(f"/v1/projects/{pid}/imports")) if b["id"] == res["batch_id"])
    ok(client.post(f"/v1/imports/{batch['id']}/review", json={"action": "accept"}))

    with SessionLocal() as db:
        rows = [r.data for r in db.scalars(select(PostRow).where(PostRow.project_id == pid))]
    ig_row = next(r for r in rows if r["channel"] == "instagram")
    yt_row = next(r for r in rows if r["channel"] == "youtube")
    assert ig_row["owner_type"] == "creator" and ig_row["sponsored"] is False
    assert yt_row["owner_type"] == "creator" and yt_row["sponsored"] is True  # isPaidPromotion=True in the fake


def test_influencer_item_marks_official_account_posts_as_self(client, fakes, monkeypatch):
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate: only the manual URL matters here
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/ig_creator/",
                                              "status": "confirmed"}]  # matches the fake instagram_post's creator
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "influencer")
    ok(client.put(f"/v1/research-items/{it['id']}/inputs", json={"post_urls": ["https://www.instagram.com/p/C1x/"]}))
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]["status"] == "succeeded"
    with SessionLocal() as db:
        row = db.scalars(select(PostRow).where(PostRow.project_id == pid)).one()
    assert row.data["owner_type"] == "self"  # 공식 계정이 올린 글이라 Owned


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
        tag = "x" if "경쟁X" in queries[0] else "y"  # each item finds its own articles, naming its own brand
        name = "경쟁X" if tag == "x" else "경쟁Y"
        res.data = {**res.data, "results": [{**r, "url": r["url"] + f"?{tag}", "title": r["title"].replace("경쟁X", name)}
                                            for r in res.data["results"]]}
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
            {"title": "경쟁X 지난해 겨울 한정판 회고 인터뷰", "url": "https://q.example.org/past", "snippet": "", "date": str(start + timedelta(days=90))},
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
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)  # isolate hashtag discovery from YouTube auto-discovery
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


def test_case_commentary_rewrite_then_accept(client, fakes):
    pid, plan = setup_project(client)
    item_ = next(i for i in plan["items"] if i["section_id"] == "campaign" and i["entity"] == "경쟁X")
    m = ok(client.post(f"/v1/projects/{pid}/materials", json={
        "title": "경쟁X 팝업 캠페인", "url": "https://example.com/campaign/x", "brand_id": "B1", "entity": "경쟁X",
        "section_id": "campaign", "research_item_id": item_["id"]}), 201)
    a = ok(client.post(f"/v1/materials/{m['id']}/assets", files={"file": ("case.png", png(), "image/png")}), 201)
    ok(client.patch(f"/v1/assets/{a['id']}", json={"review_status": "accepted"}))
    c = ok(client.post(f"/v1/materials/{m['id']}/claims", json={"kind": "fact", "text": "협업 캡슐 컬렉션 출시"}), 201)
    ok(client.patch(f"/v1/claims/{c['id']}", json={"base_version": c["version"], "review_status": "accepted"}))
    ok(client.patch(f"/v1/materials/{m['id']}/review", json={"status": "accepted"}))

    job = ok(client.post(f"/v1/projects/{pid}/case-commentary", json={}), 202)["job"]
    job = ok(client.get(f"/v1/jobs/{job['id']}"))
    assert job["state"] == "succeeded" and job["result"]["proposed"] == 1

    props = ok(client.get(f"/v1/projects/{pid}/case-commentary"))
    cc = next(p for p in props if p["material_id"] == m["id"])
    assert cc["status"] == "pending" and cc["attempts"] == 2  # first answer had a digit, the rewrite dropped it
    assert "완판" in cc["detail"] and "3" not in cc["detail"]
    ok(client.post(f"/v1/case-commentary/{cc['id']}/review", json={"action": "accept"}))

    updated = ok(client.get(f"/v1/materials/{m['id']}"))
    assert updated["ai_detail"] == cc["detail"] and updated["ai_implication"] == cc["implication"]
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert not [i for i in sp["qc"]["issues"] if i["severity"] == "block" and str(i.get("slide_id", "")).startswith("C2")]


def test_owned_item_collects_channel_facts_and_top_posts(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [
        {"channel": "instagram", "url": "https://www.instagram.com/brand1/"},
        {"channel": "youtube", "url": "https://www.youtube.com/channel/UCabc/"},
    ]
    cfg["enabled_slides"] = cfg["enabled_slides"] + ["2-1", "2-2", "2-4"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"brands": cfg["brands"], "enabled_slides": cfg["enabled_slides"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "owned")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded"
    assert fakes.calls["instagram_user_posts"] == 1 and fakes.calls["youtube_channel_videos"] == 1

    posts = ok(client.get(f"/v1/projects/{pid}/owned-posts"))
    assert len(posts) == 2  # p3 has no image_url, so only p1/p2 got downloaded
    assert [p["likes"] for p in posts] == [900, 500]  # ordered by likes desc, p2 > p1
    for p in posts:
        assert p["asset"]["review_status"] == "candidate"
        ok(client.patch(f"/v1/assets/{p['asset']['id']}", json={"review_status": "accepted"}))

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    owned_facts = [f for f in facts if f["metric"].startswith("owned_")]
    assert owned_facts  # followers, posts_monthly, likes_median, posts_by_month…
    for f in owned_facts:
        ok(client.patch(f"/v1/facts/{f['id']}/review", params={"project_id": pid}, json={"action": "confirm"}))

    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-1")["readiness"] == "ready"
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-4")["readiness"] == "ready"
    blocking = [i for i in sp["qc"]["issues"] if i["severity"] == "block" and i.get("block_id") in ("2-1", "2-2", "2-4")]
    assert blocking == [], blocking

    # rerun without force: the succeeded item is skipped, no duplicate OwnedPost rows
    job2 = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job2['id']}"))["result"]["items"][it["id"]]["status"] == "skipped"
    assert len(ok(client.get(f"/v1/projects/{pid}/owned-posts"))) == 2


def test_owned_item_also_runs_for_a_competitor_without_leaking_into_self(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/brand1/"}]
    cfg["brands"][0]["competitor_profiles"] = {
        "경쟁X": [{"channel": "instagram", "url": "https://www.instagram.com/competitorx/"}]}
    cfg["enabled_slides"] = cfg["enabled_slides"] + ["2-1"]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"brands": cfg["brands"], "enabled_slides": cfg["enabled_slides"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    self_item, comp_item = item(plan, "owned", "브랜드A"), item(plan, "owned", "경쟁X")
    assert self_item["required"] is True and comp_item["required"] is False  # 경쟁사는 선택

    # Real Instagram post ids are globally unique per account; the shared fake must vary them by
    # handle too, or the self/competitor runs collide on owned_posts' (project, channel, post_id).
    def instagram_user_posts(handle, next_max_id=None, **kw):
        fakes._hit("instagram_user_posts")
        if next_max_id:
            return CallResult(data={"posts": [], "next_max_id": None, "more_available": False}, cost_usd=0.002)
        posts = [{"post_id": f"{handle}-p1", "posted_at": "2026-08-05", "likes": 500, "comments": 10, "views": None,
                 "url": f"https://instagram.com/p/{handle}-p1/", "image_url": "https://img.example.com/p1.jpg"}]
        return CallResult(data={"posts": posts, "next_max_id": None, "more_available": False}, cost_usd=0.002)

    research.PROVIDERS["instagram_user_posts"] = instagram_user_posts

    job = ok(client.post(f"/v1/projects/{pid}/research-runs",
                         json={"item_ids": [self_item["id"], comp_item["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"]
    assert res[self_item["id"]]["status"] == "succeeded" and res[comp_item["id"]]["status"] == "succeeded"

    facts = ok(client.get(f"/v1/projects/{pid}/facts"))
    by_entity = {}
    for f in facts:
        if f["metric"] == "owned_followers" and f["dims"].get("channel") == "instagram":
            by_entity[f["entity"]] = f
    assert set(by_entity) == {"브랜드A", "경쟁X"}  # both collected, kept apart by entity

    posts = ok(client.get(f"/v1/projects/{pid}/owned-posts"))
    assert {p["entity"] for p in posts} == {"브랜드A", "경쟁X"}

    # 2-1 is self-only: confirming every owned fact must never pull 경쟁X's numbers onto 브랜드A's slide.
    for f in facts:
        if f["metric"].startswith("owned_"):
            ok(client.patch(f"/v1/facts/{f['id']}/review", params={"project_id": pid}, json={"action": "confirm"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["slot_id"] == "2-1")["readiness"] == "ready"
    build_job = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)["job"]
    ok(client.get(f"/v1/jobs/{build_job['id']}"))
    deck = ok(client.get(f"/v1/projects/{pid}/decks"))[0]
    spec = ok(client.get(f"/v1/decks/{deck['id']}"))["spec"]
    slide_2_1 = next(s for s in spec["slides"] if s["slide_id"] == "2-1")
    text = str(slide_2_1)
    assert "브랜드A" in text and "경쟁X" not in text


def test_collection_mix_flags_press_heavy_research_and_thin_channels(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    with SessionLocal() as db:
        # 3 press materials (언론) — two of them duplicates of the same activity, so only 2 count.
        srcs = [Source(id=new_id("SRC"), project_id=pid, title=f"기사{i}", source_type="web") for i in range(3)]
        db.add_all(srcs)
        db.flush()
        mats = [Material(id=new_id("EV"), project_id=pid, source_id=srcs[i].id, brand_id="B1", entity="브랜드A",
                         section_id="campaign", title=f"기사{i}", review_status="candidate") for i in range(3)]
        mats[2].duplicate_of = mats[0].id  # 같은 활동을 다룬 기사 묶음은 1건
        db.add_all(mats)
        # an unavailable (access-walled) source under the same brand
        walled_src = Source(id=new_id("SRC"), project_id=pid, title="로그인 필요", source_type="web", access_status="unavailable")
        db.add(walled_src)
        db.flush()
        db.add(Material(id=new_id("EV"), project_id=pid, source_id=walled_src.id, brand_id="B1", entity="브랜드A",
                        section_id="campaign", title="로그인 필요", review_status="excluded"))
        # 4 influencer posts (below the 10 minimum)
        for i in range(4):
            db.add(PostRow(project_id=pid, batch_id="BATCH-x", post_id=f"p{i}",
                           data={"brand_id": "B1", "owner_type": "creator"}))
        db.commit()

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["press"]["count"] == 2  # duplicate collapsed, excluded one not counted
    assert row["channels"]["influencer"] == {"count": 4, "min": 10, "enough": False,
                                             "label": "SNS·인플루언서", "action": "조사 계획에서 인플루언서 항목을 다시 모으세요"}
    assert row["channels"]["owned"]["enough"] is False and row["channels"]["owned"]["total"] == 0  # 공식 계정 미등록
    assert row["channels"]["review"] == {"count": 0, "label": "리뷰", "enough": False, "not_implemented": True}
    assert row["channels"]["cafe_blog"]["count"] == 0 and row["channels"]["cafe_blog"]["enough"] is False
    assert row["channels"]["community"]["count"] == 0 and row["channels"]["community"]["sites"] == 0
    assert row["access_unavailable"] == 1
    # press(2) / total(2 press + 4 influencer) = 1/3 ≈ 0.333 — not over 40% yet with this mix
    assert row["press_ratio"] == round(2 / 6, 3)


def test_collection_mix_community_needs_posts_spread_across_three_sites(client, fakes):
    pid, plan = setup_project(client)
    with SessionLocal() as db:
        def voc(i, url):
            src = Source(id=new_id("SRC"), project_id=pid, title=f"글{i}", original_url=url, source_type="web")
            db.add(src)
            db.flush()
            db.add(Material(id=new_id("EV"), project_id=pid, source_id=src.id, brand_id="B1", entity="브랜드A",
                            section_id="voc", title=f"글{i}", review_status="candidate"))
        # 2 cafe_blog posts (same site) + 2 community posts split across only 2 sites — short of 3.
        voc(1, "https://blog.naver.com/a/1")
        voc(2, "https://blog.naver.com/a/2")
        voc(3, "https://gall.dcinside.com/b/1")
        voc(4, "https://www.fmkorea.com/c/1")
        db.commit()

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["cafe_blog"]["count"] == 2 and row["channels"]["cafe_blog"]["enough"] is False  # 20건 미만
    assert row["channels"]["community"]["count"] == 2 and row["channels"]["community"]["sites"] == 2
    assert row["channels"]["community"]["enough"] is False  # 20건도, 3곳도 안 됨


def test_collection_mix_owned_channel_enough_once_every_confirmed_account_is_recent(client, fakes):
    pid, plan = setup_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    cfg = proj["config"]
    cfg["brands"][0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/brand1/"}]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": cfg["brands"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "owned", "브랜드A")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    assert ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]["status"] == "succeeded"

    r = ok(client.get(f"/v1/projects/{pid}/collection-mix"))
    row = next(b for b in r["brands"] if b["brand_id"] == "B1")
    assert row["channels"]["owned"] == {"count": 1, "total": 1, "enough": True, "label": "공식 채널",
                                        "action": "자료 확인에서 '다시 모으기'로 최근 자료를 받으세요"}


def test_voc_item_collects_and_classifies_consumer_posts(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "voc", "브랜드A")

    def search(queries, sites=None, **kw):
        fakes._hit("search")
        assert sites and "blog.naver.com" in sites and "dcinside.com" in sites
        return CallResult(data={"id": "s", "results": [
            {"title": "브랜드A 후기", "url": "https://blog.naver.com/x/1", "snippet": "좋아요", "date": "2026-05-01"},
            {"title": "브랜드A 솔직 후기", "url": "https://gall.dcinside.com/board/view/?id=x&no=1", "snippet": "별로", "date": "2026-05-02"},
            {"title": "브랜드A 카페 글", "url": "https://cafe.naver.com/x/2", "snippet": "", "date": "2026-05-03"},
        ]}, cost_usd=0.005)

    def fetch_page(url, **kw):
        fakes._hit("fetch_page")
        if "cafe.naver.com" in url:
            return Page(url=url, final_url="https://nid.naver.com/nidlogin.login?url=" + url, title="네이버 로그인",
                       text="로그인 후 이용해주세요", content_hash="hlogin", published=None, publisher=None, image_urls=[])
        if "dcinside" in url:
            return Page(url=url, final_url=url, title="디시 글", text="협찬 받아서 써봤는데 디자인이 별로였어요 #협찬",
                       content_hash="h2", published="2026-05-02", publisher="dcinside", image_urls=[])
        return Page(url=url, final_url=url, title="네이버 블로그 글", text="가격도 괜찮고 품질도 좋아서 친구 추천으로 알게 됐어요",
                   content_hash="h1", published="2026-05-01", publisher="네이버 블로그", image_urls=[])

    def structured(system, user, schema, **kw):
        if set(schema["properties"]) == {"relevant", "headline", "sentiment", "topic", "awareness", "sponsored"}:
            fakes._hit("voc_classify")
            if "협찬" in user:
                return CallResult(data={"relevant": True, "headline": "디자인이 별로였음", "sentiment": "negative",
                                        "topic": "design", "awareness": "other", "sponsored": True}, cost_usd=0.001)
            return CallResult(data={"relevant": True, "headline": "가격이 합리적", "sentiment": "positive",
                                    "topic": "price", "awareness": "referral", "sponsored": False}, cost_usd=0.001)
        return fakes.structured(system, user, schema, **kw)

    research.PROVIDERS["search"] = search
    research.PROVIDERS["fetch_page"] = fetch_page
    research.PROVIDERS["structured"] = structured

    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["created"] == 3 and res["access_unavailable"] == 1
    assert res["channels"] == {"cafe_blog": 1, "community": 1}
    assert fakes.calls["voc_classify"] == 2  # the login-walled card never reaches AI classification

    mats = {m["source"]["url"]: m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["section_id"] == "voc"}
    blog = mats["https://blog.naver.com/x/1"]
    assert blog["voc_sentiment"] == "positive" and blog["voc_topic"] == "price" and blog["voc_awareness"] == "referral"
    assert blog["voc_sponsored"] is False
    dc = mats["https://gall.dcinside.com/board/view/?id=x&no=1"]
    assert dc["voc_sponsored"] is True
    walled = mats["https://cafe.naver.com/x/2"]
    assert walled["source"]["access_status"] == "unavailable"

    # 묶음 채택: 접근 불가·협찬 표기 카드는 사람의 확인을 기다리고, 나머지만 한 번에 채택된다.
    out = ok(client.post(f"/v1/projects/{pid}/materials/accept-all"))
    assert out["accepted"] == 1 and out["left"] == 2


def test_voc_item_reports_access_cause_when_every_post_is_login_walled(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    proj = ok(client.get(f"/v1/projects/{pid}"))
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"],
                                                 "changes": {"enabled_slides": proj["config"]["enabled_slides"] + ["5-1"]}}))
    plan = ok(client.get(f"/v1/projects/{pid}/research-plan"))
    it = item(plan, "voc", "브랜드A")

    def search(queries, sites=None, **kw):
        return CallResult(data={"id": "s", "results": [
            {"title": "브랜드A 카페 글", "url": "https://cafe.naver.com/x/9", "snippet": "", "date": "2026-05-03"}]},
                          cost_usd=0.005)

    def fetch_page(url, **kw):
        return Page(url=url, final_url="https://nid.naver.com/nidlogin.login", title="네이버 로그인",
                   text="로그인 후 이용해주세요", content_hash="hlogin", published=None, publisher=None, image_urls=[])

    research.PROVIDERS["search"] = search
    research.PROVIDERS["fetch_page"] = fetch_page
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    slot = next((s for s in sp["plan"] if s["slot_id"].startswith("5-1")), None)
    assert slot is not None and slot["readiness"] == "needs_input" and slot["cause"] == "access"


def test_research_runs_without_a_run_budget(client, fakes, monkeypatch):
    """No RUN_BUDGET_USD = no cap: the run goes ahead and its cost is still recorded."""
    monkeypatch.delenv("RUN_BUDGET_USD", raising=False)
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁Y")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] != "blocked_budget" and fakes.calls.get("search", 0) > 0
    assert any(r.status == "settled" for r in ledger_rows(pid))


def test_project_list_shows_total_cost(client):
    pid, _ = setup_project(client)
    with SessionLocal() as db:  # cached responses cost nothing, so record spend directly
        db.add_all([ProviderCall(project_id=pid, provider="perplexity", endpoint="search", fingerprint="a",
                                 status="settled", cost_usd=0.005),
                    ProviderCall(project_id=pid, provider="anthropic", endpoint="extract", fingerprint="b",
                                 status="settled", cost_usd=0.0125)])
        db.commit()
    row = next(p for p in ok(client.get("/v1/projects")) if p["id"] == pid)
    assert row["total_cost_usd"] == 0.0175


def test_direction_chat_rewrites_the_item_and_the_plan(client, fakes):
    pid, plan = setup_project(client)
    version = ok(client.get(f"/v1/projects/{pid}"))["version"]
    out = ok(client.post(f"/v1/projects/{pid}/scope/3-7/direction",
                         json={"base_version": version, "message": "경쟁X만, 1년치 팝업 위주로 4개씩"}))
    assert out["reply"].startswith("기간을") and out["project_version"] == version + 1
    sc = out["scope"]
    assert sc["period"] == "months" and sc["months"] == 12 and sc["channels"] == ["web", "instagram"]  # unknown dropped
    assert sc["targets"] == ["경쟁X"] and sc["max_items"] == 4 and sc["keywords"] == ["팝업스토어"]
    assert sc["direction"][-1] == "팝업·오프라인 행사 사례를 먼저 봅니다."
    items = [i for i in ok(client.get(f"/v1/projects/{pid}/research-plan"))["items"] if i["scope_id"] == "3-7"]
    assert [i["entity"] for i in items] == ["경쟁X"] and items[0]["period_start"] == "2025-10-01"
    # A stale version is refused instead of overwriting someone else's change.
    r = client.post(f"/v1/projects/{pid}/scope/3-7/direction", json={"base_version": version, "message": "x"})
    assert r.status_code == 409


def test_card_ai_help_summary_suggestions_polish_chat(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:  # an earlier test caches search results that point elsewhere
        db.query(ProviderCache).delete()
        db.commit()
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    article = next(m for m in ok(client.get(f"/v1/projects/{pid}/materials")) if m["source"]["url"] == "https://news.example.com/a1")

    # A hand-made card gets its 해석 요약 on request (page fetched once and kept).
    manual = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "직접", "url": "https://example.com/m",
                                                                    "section_id": "campaign"}), 201)
    assert ok(client.post(f"/v1/materials/{manual['id']}/summary"))["summary"] == "직접 만든 카드의 요약입니다."

    # Sentence ideas: only the one quoting the page verbatim, with no bare number, survives.
    sug = ok(client.post(f"/v1/materials/{article['id']}/claim-suggestions"))["suggestions"]
    assert [s["text"] for s in sug] == ["성수동 팝업에 신제품 체험 공간 배치"]
    c = ok(client.post(f"/v1/materials/{article['id']}/claims", json={**sug[0], "accept": True}), 201)
    assert c["review_status"] == "accepted" and c["author"] == "ai" and c["quote"]

    # 다듬기 keeps the fact token; a rewrite that changes numbers is refused.
    fid = article["facts"][0]["id"]
    text = "조회 {{" + fid + "}} 규모의 체험형 확산"
    assert ok(client.post(f"/v1/materials/{article['id']}/polish", json={"text": text}))["text"].count(fid) == 1
    r = client.post(f"/v1/materials/{article['id']}/polish", json={"text": text + " 깨기"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "POLISH_CHANGED_FACTS"

    # Chat: the page does not say, so it searches once and cites only results that exist.
    out = ok(client.post(f"/v1/materials/{article['id']}/chat", json={"message": "방문객이 언제 몰렸어?"}))
    assert out["searched"] == "경쟁X 팝업 방문객" and out["answer"].startswith("추가 기사")
    assert out["sources"] == [{"title": "경쟁X 성수 팝업", "url": "https://news.example.com/a1"}]


def test_outline_reads_the_deck_and_slide_feedback_changes_it(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    flow = ok(client.get(f"/v1/projects/{pid}/outline"))
    slides = [x for x in flow["flow"] if x["kind"] == "slide"]
    assert any(x["kind"] == "section" for x in flow["flow"]) and flow["missing"]  # empty slides are listed, not shown
    share = next(x for x in slides if x["slide_id"] == "2-8a")
    assert share["lead"] and share["points"] and share["source"] and not share["edited"]

    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "리드를 좀 더 부드럽게"}))
    assert out["action"] == "rewrite_lead"
    share = next(x for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x.get("slide_id") == "2-8a")
    assert share["edited"] and share["lead"] == "브랜드 검색 점유 우위가 줄어든 흐름"

    # A headline that breaks the rules (bare number) is retried, then left alone with a plain reason.
    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "깨기"}))
    assert out["action"] == "none" and "규칙" in out["reply"]
    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "순서를 앞으로"}))
    assert out["action"] == "none" and "순서" in out["reply"]

    out = ok(client.post(f"/v1/projects/{pid}/outline/2-8a/feedback", json={"message": "이 장은 빼줘"}))
    assert out["action"] == "omit" and out["slot_id"] == "2-8a"
    after = ok(client.get(f"/v1/projects/{pid}/outline"))
    assert "2-8a" not in [x.get("slide_id") for x in after["flow"]] and after["omitted"][0]["slot_id"] == "2-8a"
    assert client.post(f"/v1/projects/{pid}/outline/nope/feedback", json={"message": "x"}).status_code == 404


def test_accept_all_takes_waiting_cards_and_leaves_doubtful_ones(client, fakes):
    pid, _ = setup_project(client)
    plain = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "직접 넣은 사례", "section_id": "campaign"}), 201)
    doubtful = ok(client.post(f"/v1/projects/{pid}/materials", json={"title": "기간 애매", "section_id": "campaign"}), 201)
    with SessionLocal() as db:
        from app.models import Material
        db.get(Material, doubtful["id"]).review_reason = "기간 확인 필요: 활동일·발행일 미확인"
        db.commit()
    c = ok(client.post(f"/v1/materials/{plain['id']}/claims", json={"kind": "fact", "text": "팝업 운영"}), 201)
    out = ok(client.post(f"/v1/projects/{pid}/materials/accept-all"))
    assert out == {"accepted": 1, "left": 1}
    m = ok(client.get(f"/v1/materials/{plain['id']}"))
    assert m["review_status"] == "accepted" and m["claims"][0]["review_status"] == "accepted" and m["claims"][0]["id"] == c["id"]
    assert ok(client.get(f"/v1/materials/{doubtful['id']}"))["review_status"] == "candidate"


def test_results_that_never_name_the_brand_are_dropped_before_fetching(client, fakes):
    pid, plan = setup_project(client)
    it = item(plan, "campaign", "경쟁X")
    with SessionLocal() as db:
        db.query(ProviderCache).delete()
        db.commit()
    original = fakes.search

    def noisy(queries, **kw):
        res = original(queries, **kw)
        res.data = {**res.data, "results": [
            {"title": "코웨이, 연중 최대 프로모션 개최", "url": "https://n.example.com/coway", "snippet": "렌탈료 할인", "date": "2026-03-01"},
            {"title": "패션 브리핑", "url": "https://n.example.com/brief", "snippet": "경쟁 X 가 새 컬렉션을 공개", "date": "2026-03-02"},
            *res.data["results"]]}
        return res

    research.PROVIDERS["search"] = noisy
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    urls = [m["source"]["url"] for m in ok(client.get(f"/v1/projects/{pid}/materials"))]
    assert "https://n.example.com/coway" not in urls and res["off_topic"] >= 1
    assert "https://n.example.com/brief" in urls  # named in the snippet (spacing ignored) still counts


def test_synthesis_writes_summary_pages_from_the_deck(client, fakes):
    pid, _ = setup_project(client)
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    brand_id = ok(client.get(f"/v1/projects/{pid}"))["config"]["brands"][0]["id"]

    out = ok(client.post(f"/v1/projects/{pid}/synthesis", json={"brand_id": brand_id, "instruction": "검색 위주로"}))
    assert out["version"] == 1 and out["active"] and not out["stale"]
    assert out["types"] == ["insight"]  # 기본값
    assert out["data"]["insight"]["competitor"] == ["경쟁 세트 안 검색 점유 우위 축소"]  # 숫자 포함 줄과 없는 장표 참조 줄은 빠짐
    assert any("숫자" in d for d in out["dropped"]) and any("Z-9" in d for d in out["dropped"])
    flow = ok(client.get(f"/v1/projects/{pid}/outline"))["flow"]
    ids = [x.get("slide_id") for x in flow if x["kind"] == "slide"]
    assert ids[0] == "ES" and "INSIGHT" in ids and "SWOT" not in ids  # 고른 유형만 만들어진다
    issues = ok(client.get(f"/v1/projects/{pid}/slide-plan"))["qc"]["issues"]
    assert not [i for i in issues if i["slide_id"] in ("ES", "INSIGHT") and i["severity"] == "block"], issues

    # 다시 쓰기: 결과가 이미 있어도 다시 쓸 수 있고, 덮어쓰지 않고 새 버전으로 남는다(버그 수정 확인).
    out2 = ok(client.post(f"/v1/projects/{pid}/synthesis",
                          json={"brand_id": brand_id, "types": ["insight", "swot"], "instruction": "검색 위주로"}))
    assert out2["version"] == 2 and out2["active"] and out2["types"] == ["insight", "swot"]
    versions = ok(client.get(f"/v1/projects/{pid}/synthesis"))
    assert [(v["version"], v["active"]) for v in versions] == [(2, True), (1, False)]
    ids2 = [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x["kind"] == "slide"]
    assert "SWOT" in ids2  # 새 버전의 유형이 반영됨

    # 되돌리기: 새로 만들지 않고 이전 버전을 다시 활성으로.
    v1 = next(v for v in versions if v["version"] == 1)
    back = ok(client.post(f"/v1/synthesis-runs/{v1['id']}/activate"))
    assert back["active"] and back["version"] == 1
    versions = ok(client.get(f"/v1/projects/{pid}/synthesis"))
    assert [(v["version"], v["active"]) for v in versions] == [(2, False), (1, True)]
    ids3 = [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"] if x["kind"] == "slide"]
    assert "SWOT" not in ids3  # v1에는 insight만 있었으므로 되돌아감

    ok(client.delete(f"/v1/projects/{pid}/synthesis", params={"brand_id": brand_id}))
    assert "ES" not in [x.get("slide_id") for x in ok(client.get(f"/v1/projects/{pid}/outline"))["flow"]]


def test_synthesis_scopes_pages_to_their_own_brand(client, fakes, monkeypatch):
    """자사 브랜드가 여럿이면 브랜드마다 따로 — 다른 브랜드의 본문 장표가 섞이지 않는다."""
    from app.models import Project

    p = ok(client.post("/v1/projects", json={
        "name": "멀티 브랜드", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X1"], "categories": ["러기지"]},
                  {"id": "B2", "name": "브랜드B", "competitors": ["경쟁Y1"], "categories": ["러기지"]}]}), 201)
    pid = p["id"]

    pages = [{"id": "1-1", "chapter": "company", "title": "자사 채널 A", "lead": "A 운영 현황", "points": [], "brand": "브랜드A"},
             {"id": "1-2", "chapter": "company", "title": "자사 채널 B", "lead": "B 운영 현황", "points": [], "brand": "브랜드B"},
             {"id": "3-1", "chapter": "customer", "title": "검색 추이", "lead": "검색 추이 공유", "points": []}]
    monkeypatch.setattr(synthesis, "body_pages", lambda db, project: pages)

    seen: list[str] = []

    def fake_structured(system, user, schema, **kw):
        seen.append(user)
        return CallResult(data={"es_company": [], "es_competitor": [], "es_customer": [], "task": "", "insights": []},
                          usage={"model": "fake"}, cost_usd=0.001)

    synthesis.STRUCTURED.clear()
    synthesis.STRUCTURED.append(fake_structured)
    try:
        with SessionLocal() as db:
            project = db.get(Project, pid)
            synthesis.generate(db, project, "B1", ["insight"])
            synthesis.generate(db, project, "B2", ["insight"])
            db.rollback()
    finally:
        synthesis.STRUCTURED.clear()

    assert "1-1" in seen[0] and "3-1" in seen[0] and "1-2" not in seen[0]  # B1: 자신의 장표 + 공유 장표만
    assert "1-2" in seen[1] and "3-1" in seen[1] and "1-1" not in seen[1]  # B2: 자신의 장표 + 공유 장표만


def test_articles_naming_a_competitor_another_way_are_kept(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    fakes.search_name = "CompetitorX"  # every article uses the English name only
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "succeeded" and res["created"] == 2 and res["off_topic"] == 0
    brand = ok(client.get(f"/v1/projects/{pid}"))["config"]["brands"][0]
    assert brand["entity_aliases"]["경쟁X"] == ["CompetitorX"]  # filled by the AI, the name itself left out


def test_no_material_about_the_subject_is_reported_and_not_bulk_confirmed(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    fakes.search_name = "다른브랜드"
    it = item(plan, "campaign", "경쟁X")
    job = ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)["job"]
    res = ok(client.get(f"/v1/jobs/{job['id']}"))["result"]["items"][it["id"]]
    assert res["status"] == "failed" and res.get("created", 0) == 0
    assert res["errors"][0]["code"] == "NO_MATERIAL" and res["retried_aliases"] == ["CompetitorX"]
    assert fakes.calls["aliases"] == 1
    ok(client.post(f"/v1/projects/{pid}/research-plan/accept-all"))
    after = item(ok(client.get(f"/v1/projects/{pid}/research-plan")), "campaign", "경쟁X")
    assert after["review_status"] == "pending"


def test_create_project_fills_industry_and_official_accounts(client, fakes):
    clear_cache()  # another test may have cached a request with the same (provider, endpoint, name)
    p = ok(client.post("/v1/projects", json={
        "name": "브랜드 카드 테스트", "client": "고객", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"], "categories": ["러기지"]}]}), 201)
    brand = p["config"]["brands"][0]
    assert brand["industry"] == "패션"  # AI가 채움, 사람이 입력하지 않음
    assert [prof["status"] for prof in brand["official_profiles"]] == ["candidate"]  # 확인 전까지는 후보일 뿐
    assert brand["competitor_profiles"]["경쟁X"][0]["channel"] == "instagram"
    assert fakes.calls["industry"] == 1
    assert fakes.calls["official_accounts"] == 2  # self + 경쟁X, 한 번씩

    # A planner-set industry is never overwritten, and an entity with an account already on file
    # (even just a candidate) is not searched again.
    pid = p["id"]
    patched = ok(client.patch(f"/v1/projects/{pid}", json={"base_version": p["version"], "changes": {
        "brands": [{**brand, "industry": "뷰티"}]}}))
    assert patched["config"]["brands"][0]["industry"] == "뷰티"
    assert fakes.calls["industry"] == 1  # still just the one call from create
    assert fakes.calls["official_accounts"] == 2


def test_missing_slides_say_why_and_what_to_do(client, fakes):
    pid, plan = setup_project(client)
    clear_cache()
    it = item(plan, "campaign", "경쟁X")
    ok(client.post(f"/v1/projects/{pid}/research-runs", json={"item_ids": [it["id"]]}), 202)
    gaps = {s["slot_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"] if s["readiness"] == "needs_input"}
    assert gaps["C1c"]["cause"] == "adopt"  # 경쟁X's cards are waiting for a person
    # 3-1(인플루언서)은 이제 입력이 없어도 브랜드 이름으로 찾아보므로 '설정 필요'가 아니라 '수집 필요'.
    assert gaps["2-8a"]["cause"] == "upload" and gaps["3-1-B1"]["cause"] == "collect"
    self_item = item(plan, "campaign", "브랜드A")
    assert gaps["C1"]["cause"] == "collect" and gaps["C1"]["item_ids"] == [self_item["id"]]
    assert gaps["5-recap"]["cause"] is None
    missing = {m["slot_id"]: m for m in ok(client.get(f"/v1/projects/{pid}/outline"))["missing"]}
    assert missing["C1c"]["cause"] == "adopt" and missing["C1c"]["action"]
