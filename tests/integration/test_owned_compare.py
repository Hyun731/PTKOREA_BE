"""P3-1 자사 vs 경쟁사 채널 비교 — 수집된 경쟁사 공식 계정 수치가 확인을 거쳐 장표까지 오는지."""
import json
from datetime import date
from decimal import Decimal

from app.db import SessionLocal
from app.models import FactRow
from core.ingestion.owned import owned_fact


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def sample_project(client, slides=("2-1",)):
    p = ok(client.post("/v1/projects/sample"), 201)
    proj = ok(client.get(f"/v1/projects/{p['id']}"))
    enabled = proj["config"]["enabled_slides"] + [s for s in slides if s not in proj["config"]["enabled_slides"]]
    ok(client.patch(f"/v1/projects/{p['id']}", json={"base_version": proj["version"],
                                                     "changes": {"enabled_slides": enabled}}))
    return p["id"]


OWNED = {"브랜드A": {"owned_followers": 10461, "owned_posts_monthly": "7.78", "owned_likes_median": 224},
         "경쟁X": {"owned_followers": 19116, "owned_posts_monthly": "13.22", "owned_likes_median": 136},
         "경쟁Y": {"owned_followers": 9418, "owned_posts_monthly": "3.11", "owned_likes_median": 17}}


def add_owned_facts(pid: str, data=OWNED, channel="instagram", brand_id="B1") -> list[str]:
    ids = []
    with SessionLocal() as db:
        for entity, metrics in data.items():
            for metric, value in metrics.items():
                f = owned_fact(brand_id=brand_id, entity=entity, metric=metric, value=Decimal(str(value)),
                               channel=channel, period_start=date(2026, 1, 1), period_end=date(2026, 9, 30),
                               measured_at=date(2026, 10, 1), label=f"{entity} {metric}")
                db.add(FactRow(project_id=pid, fact_id=f.id, origin="auto", data=json.loads(f.model_dump_json()),
                               verification_status="candidate"))
                ids.append(f.id)
        db.commit()
    return ids


def test_competitor_owned_numbers_wait_for_confirmation_then_fill_the_compare_page(client):
    pid = sample_project(client)
    ids = add_owned_facts(pid)
    gaps = {s["template_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"]
            if s["readiness"] == "needs_input"}
    assert gaps["OW-CMP"]["cause"] == "adopt" and "수치" in gaps["OW-CMP"]["action"]

    for fid in ids:
        ok(client.patch(f"/v1/facts/{fid}/review", params={"project_id": pid}, json={"action": "confirm"}))
    sp = ok(client.get(f"/v1/projects/{pid}/slide-plan"))
    assert next(s for s in sp["plan"] if s["template_id"] == "OW-CMP")["readiness"] == "ready"
    pages = [p["slide_id"] for p in sp["pages"]]
    assert pages.index("OW-CMP") == pages.index("2-1") + 1
    blocking = [i for i in sp["qc"]["issues"] if i["severity"] == "block" and str(i.get("slide_id")).startswith("OW-CMP")]
    assert blocking == [], blocking

    build_job = ok(client.post(f"/v1/projects/{pid}/deck-builds"), 202)["job"]
    ok(client.get(f"/v1/jobs/{build_job['id']}"))
    deck = ok(client.get(f"/v1/projects/{pid}/decks"))[0]
    spec = ok(client.get(f"/v1/decks/{deck['id']}"))["spec"]
    page = next(s for s in spec["slides"] if s["slide_id"] == "OW-CMP")
    bound = {(b["entity"], b["metric"]) for b in page["bindings"]}
    assert ("경쟁X", "owned_followers") in bound and ("브랜드A", "owned_followers") in bound
    # 2-1 stays self-only
    assert "경쟁X" not in str(next(s for s in spec["slides"] if s["slide_id"] == "2-1"))


def test_without_competitor_accounts_the_page_asks_for_them_in_settings(client):
    pid = sample_project(client)
    proj = ok(client.get(f"/v1/projects/{pid}"))
    brands = proj["config"]["brands"]
    brands[0]["official_profiles"] = [{"channel": "instagram", "url": "https://www.instagram.com/brand1/",
                                       "status": "confirmed"}]
    ok(client.patch(f"/v1/projects/{pid}", json={"base_version": proj["version"], "changes": {"brands": brands}}))
    gaps = {s["template_id"]: s for s in ok(client.get(f"/v1/projects/{pid}/slide-plan"))["plan"]
            if s["readiness"] == "needs_input"}
    assert gaps["OW-CMP"]["cause"] == "setup" and "경쟁사 공식 계정" in gaps["OW-CMP"]["action"]
