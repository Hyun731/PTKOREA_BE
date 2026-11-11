"""P5-1 진단 플래너: 덱을 만들 때 자동 실행·fingerprint 캐시, 진단 탭 API(보기·빼기·고치기·다시 쓰기·되돌리기)."""
import re

from app.db import SessionLocal
from app.models import Project
from app.services import diagnosis
from app.services.inputs import load_inputs
from integrations.base import CallResult


def ok(r, status=200):
    assert r.status_code == status, r.text
    return r.json()


def _refs(user: str, label: str) -> dict[str, str]:
    """{entity: ref} for the fact lines with this label (first match per entity)."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^(F\d+): [^·]+ · ([^·]+) · " + label + r"(?: · window=12M, seg=all)?$", user, re.M):
        out.setdefault(m.group(2).strip(), m.group(1))
    return out


def fake_answer(user: str) -> dict:
    share = _refs(user, "검색 점유")
    me, rival = share["브랜드A"], share["경쟁X"]

    def s(text="", ref=None, accent=False):
        return {"text": text, "fact_ref": ref, "accent": accent}

    return {
        "profile": "브랜드명 검색은 앞서고, 카테고리 탐색에서 밀리는 브랜드",
        "funnel": [{"stage": "인지", "fact_ref": me, "label": "브랜드명 검색 점유", "status": "강점"},
                   {"stage": "탐색", "fact_ref": None, "label": "카테고리 탐색", "status": "이탈"}],
        "claims": [
            {"kind": "strength", "claim": [s("브랜드명 검색은 경쟁 세트 "), s("선두", accent=True)],
             "evidence": [[s("브랜드명 검색 점유 "), s(ref=me), s(" vs 경쟁X "), s(ref=rival)]],
             "chart": {"type": "bar", "fact_refs": [me, rival]}, "quote_refs": []},
            {"kind": "weakness", "claim": [s("경쟁X와 검색 점유 격차가 "), s("좁아짐", accent=True)],
             "evidence": [[s("경쟁X 검색 점유 "), s(ref=rival)]],
             "chart": {"type": "line", "fact_refs": [me, rival]}, "quote_refs": []},
        ],
        "cdj": [{"stage": "탐색", "touchpoint": "포털 검색", "state": "카테고리로 찾음", "activity": "조합어 콘텐츠"}],
        "proposals": [{"pillar": "콘텐츠", "title": "카테고리 조합어 콘텐츠", "cdj_stage": "탐색",
                       "basis_fact_refs": [rival], "basis": [s("경쟁X 검색 점유 "), s(ref=rival)]}],
    }


def _stub(calls: list):
    def structured(system, user, schema, **kw):
        calls.append(user)
        return CallResult(data=fake_answer(user), usage={"model": "fake"}, cost_usd=0.001)
    return structured


def test_diagnosis_is_written_once_per_materials_and_edited_in_the_tab(client):
    pid = ok(client.post("/v1/projects/sample"), 201)["id"]
    for b in ok(client.post(f"/v1/projects/{pid}/imports/sample"), 201):
        ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    calls: list[str] = []
    diagnosis.STRUCTURED.clear()
    diagnosis.STRUCTURED.append(_stub(calls))
    try:
        with SessionLocal() as db:
            project = db.get(Project, pid)
            first = diagnosis.ensure(db, project)
            assert [g["brand_id"] for g in first["generated"]] == ["B1"] and len(calls) == 1
            again = diagnosis.ensure(db, project)  # same materials: the stored version is reused
            assert again["cached"] == ["B1"] and len(calls) == 1
            inputs = load_inputs(db, project)
            assert inputs.diagnosis["B1"]["profile"].startswith("브랜드명 검색은")

        tab = ok(client.get(f"/v1/projects/{pid}/diagnosis"))
        b1 = tab[0]
        assert b1["brand_id"] == "B1" and b1["active"] == 1 and not b1["stale"]
        claims = b1["data"]["claims"]
        assert [c["kind"] for c in claims] == ["strength", "weakness"] and b1["claim_labels"]["c1"] == "강점"
        assert claims[1]["chart"]["type"] == "bar"  # two values that are not a time series: no line chart
        assert b1["data"]["proposals"][0]["basis_fact_ids"]

        # 빼기 → a new version a person made; the deck build keeps it
        out = ok(client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c2", json={"excluded": True}))
        assert out["active"] == 2 and out["data"]["claims"][1]["excluded"] and out["versions"][0]["origin"] == "edit"
        # 문장 고치기: numbers stay fact parts; a bare digit is refused
        fact = next(p for p in claims[0]["evidence"][0]["parts"] if p["type"] == "fact")
        edited = {"claim": [{"parts": [{"type": "text", "text": "브랜드명 검색 점유 1위 유지"}]}]}
        bad = client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c1", json=edited)
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "CLAIM_RULES"
        edited = {"claim": [{"parts": [{"type": "text", "text": "브랜드명 검색 점유 "},
                                       {"type": "text", "text": "선두 유지", "color": "accent"}]}],
                  "evidence": [{"parts": [{"type": "text", "text": "점유 "}, {**fact, "display": "999%"}]}]}
        out = ok(client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c1", json=edited))
        c1 = out["data"]["claims"][0]
        assert c1["edited"] and c1["evidence"][0]["parts"][1]["display"] == fact["display"]  # re-formatted
        unknown = {"evidence": [{"parts": [{"type": "fact", "fact_id": "F-nope", "formatter": "share"}]}]}
        assert client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c1", json=unknown).status_code == 422
        assert client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c9", json={"excluded": True}).status_code == 404

        with SessionLocal() as db:
            assert diagnosis.ensure(db, db.get(Project, pid))["cached"] == ["B1"]  # the edit stays

        # 다시 쓰기 with a request, then 되돌리기 to the person's version
        out = ok(client.post(f"/v1/projects/{pid}/diagnosis", json={"brand_id": "B1", "instruction": "약점을 먼저"}))
        assert out["active"] == 4 and out["versions"][0]["origin"] == "rewrite" and len(calls) == 2
        assert "<request>\n약점을 먼저" in calls[-1]
        out = ok(client.post(f"/v1/projects/{pid}/diagnosis/B1/versions/3/activate"))
        assert out["active"] == 5 and out["versions"][0]["origin"] == "restore"
        assert out["data"]["claims"][0]["edited"]
        assert client.post(f"/v1/projects/{pid}/diagnosis/B1/versions/99/activate").status_code == 404
    finally:
        diagnosis.STRUCTURED.clear()


def test_diagnosis_tab_without_ai_or_brand(client):
    pid = ok(client.post("/v1/projects/sample"), 201)["id"]
    tab = ok(client.get(f"/v1/projects/{pid}/diagnosis"))
    assert tab[0]["data"] is None and tab[0]["versions"] == []
    r = client.post(f"/v1/projects/{pid}/diagnosis", json={"brand_id": "B1"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"
    assert client.post(f"/v1/projects/{pid}/diagnosis", json={"brand_id": "B9"}).status_code == 404
    assert client.patch(f"/v1/projects/{pid}/diagnosis/B1/claims/c1", json={"excluded": True}).status_code == 404
