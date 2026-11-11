"""P3-2 GET /projects/{id}/owned-summary — 자사 분석 / 경쟁사 비교 탭 데이터(읽기 전용)."""
import json
from datetime import date
from decimal import Decimal

from app.db import SessionLocal
from app.models import FactRow, OwnedPost, new_id
from core.ingestion.csv_import import content_hash, fact_id_from_hash
from core.ingestion.owned import monthly_post_count_fact
from core.schemas.facts import Fact
from tests.integration.test_owned_compare import OWNED, add_owned_facts, ok, sample_project


def add_fact(pid, metric, value, entity, unit="count", status="candidate", **dims):
    payload = {"m": metric, "e": entity, "v": str(value), "d": dims}
    h = content_hash(payload)
    f = Fact(id=fact_id_from_hash(h), content_hash=h, brand_id="B1", entity=entity, metric=metric,
             value=Decimal(str(value)), unit=unit, dims={k: str(v) for k, v in dims.items()},
             period_start=date(2026, 1, 1), period_end=date(2026, 9, 30), measured_at=date(2026, 10, 1),
             source="테스트", confidence="verified", source_locator="https://blog.naver.com/a/1,https://cafe.naver.com/b/2")
    with SessionLocal() as db:
        db.add(FactRow(project_id=pid, fact_id=f.id, origin="auto", data=json.loads(f.model_dump_json()),
                       verification_status=status))
        db.commit()
    return f.id


def summary(client, pid, **params):
    return ok(client.get(f"/v1/projects/{pid}/owned-summary", params=params))


def test_empty_project_says_what_fills_the_tab(client):
    pid = sample_project(client)
    s = summary(client, pid)
    assert s["brand"] == {"id": "B1", "name": "브랜드A"}
    assert [e["role"] for e in s["entities"]] == ["self", "competitor", "competitor"]
    assert s["channels"] == [] and s["has_data"] is False
    assert s["empty"]["message"] == "공식 계정을 등록하면 자동으로 채워집니다"
    assert s["empty"]["settings_path"] == f"/projects/{pid}/setup"
    r = client.get(f"/v1/projects/{pid}/owned-summary", params={"brand_id": "NOPE"})
    assert r.status_code == 404


def test_channel_kpis_show_candidates_flagged_and_the_gap_to_the_top_competitor(client):
    pid = sample_project(client)
    ids = add_owned_facts(pid)
    yt = {"브랜드A": {"owned_followers": 9500}, "경쟁X": {"owned_followers": 12000}}
    add_owned_facts(pid, yt, channel="youtube")
    with SessionLocal() as db:
        for e, counts in (("브랜드A", (9, 12)), ("경쟁X", (13, 16))):
            for month, n in zip(("2026-01", "2026-02"), counts):
                f = monthly_post_count_fact(brand_id="B1", entity=e, channel="instagram", month=month, count=n,
                                            measured_at=date(2026, 10, 1))
                db.add(FactRow(project_id=pid, fact_id=f.id, origin="auto", data=json.loads(f.model_dump_json()),
                               verification_status="eligible"))
        db.commit()
    ok(client.patch(f"/v1/facts/{ids[0]}/review", params={"project_id": pid}, json={"action": "confirm"}))
    ok(client.patch(f"/v1/facts/{ids[-1]}/review", params={"project_id": pid},
                    json={"action": "reject", "note": "다른 계정"}))

    s = summary(client, pid, brand_id="B1")
    assert s["has_data"] and s["empty"] is None
    assert [c["channel"] for c in s["channels"]] == ["instagram", "youtube"]
    ig = s["channels"][0]
    followers = next(k for k in ig["kpis"] if k["key"] == "followers")
    assert [(v["entity"], v["display"], v["status"]) for v in followers["values"]] == [
        ("브랜드A", "10,461", "eligible"), ("경쟁X", "19,116", "candidate"), ("경쟁Y", "9,418", "candidate")]
    assert followers["vs_competitor"] == {"competitor": "경쟁X", "diff": -8655.0, "ratio_pct": 54.7}
    likes = next(k for k in ig["kpis"] if k["key"] == "likes")
    assert [v["entity"] for v in likes["values"]] == ["브랜드A", "경쟁X"]  # 경쟁Y의 좋아요는 제외(rejected)
    months = ig["monthly_posts"]
    assert months["months"] == ["2026-01", "2026-02"]
    assert [(x["entity"], [p["value"] for p in x["points"]]) for x in months["series"]] == [
        ("브랜드A", [9.0, 12.0]), ("경쟁X", [13.0, 16.0])]


def test_sentiment_pain_points_blog_types_and_mentions(client):
    pid = sample_project(client)
    with SessionLocal() as db:
        for e, (pos, neg, neu) in (("브랜드A", (12, 4, 4)), ("경쟁X", (5, 10, 5))):
            db.add(OwnedPost(id=new_id("OP"), project_id=pid, brand_id="B1", entity=e, channel="instagram",
                             post_id=f"{e}-1", comment_sentiment={"positive": pos, "negative": neg, "neutral": neu,
                                                                  "sample_size": pos + neg + neu}))
        db.commit()
    add_fact(pid, "pain_point_count", 14, "브랜드A", pain_point="바퀴 소음", n=80)
    add_fact(pid, "pain_point_count", 9, "브랜드A", pain_point="가격", n=80)
    for t, v in (("real_use", "40.0"), ("sponsored", "33.3"), ("other", "26.7")):
        add_fact(pid, "blog_type_share", v, "브랜드A", unit="percent", keyword="브랜드A 캐리어", type=t, n=30)
    add_fact(pid, "mention_total", 12034, "브랜드A", channel="blog", keyword_group="brand", keyword="브랜드A")
    add_fact(pid, "mention_total", 3021, "경쟁X", channel="cafe", keyword_group="brand", keyword="경쟁X")

    s = summary(client, pid)
    ig = next(c for c in s["channels"] if c["channel"] == "instagram")
    assert ig["kpis"] == []  # 지표 수치는 없어도 감성만으로 채널 카드가 생긴다
    sent = {x["entity"]: x for x in ig["sentiment"]}
    assert sent["브랜드A"]["n"] == 20 and sent["브랜드A"]["method"] == "AI 분류"
    assert [(r["label"], r["display"], r["status"]) for r in sent["브랜드A"]["rates"]] == [
        ("긍정", "60.0%", "derived"), ("중립", "20.0%", "derived"), ("부정", "20.0%", "derived")]
    assert [(p["pain_point"], p["display"], p["n"]) for p in s["pain_points"]] == [("바퀴 소음", "14", 80), ("가격", "9", 80)]
    assert s["pain_points"][0]["examples"] == ["https://blog.naver.com/a/1", "https://cafe.naver.com/b/2"]
    bt = s["blog_types"][0]
    assert bt["keyword"] == "브랜드A 캐리어" and bt["n"] == 30
    assert [(x["label"], x["display"]) for x in bt["shares"]] == [("실사용", "40.0%"), ("협찬", "33.3%"), ("기타", "26.7%")]
    assert [(m["entity"], m["channel_label"], m["display"]) for m in s["mentions"]] == [
        ("브랜드A", "블로그", "12,034"), ("경쟁X", "카페", "3,021")]


def test_summary_never_writes(client):
    pid = sample_project(client)
    add_owned_facts(pid, {"브랜드A": OWNED["브랜드A"]})
    with SessionLocal() as db:
        before = db.query(FactRow).filter(FactRow.project_id == pid).count()
    summary(client, pid)
    with SessionLocal() as db:
        assert db.query(FactRow).filter(FactRow.project_id == pid).count() == before
