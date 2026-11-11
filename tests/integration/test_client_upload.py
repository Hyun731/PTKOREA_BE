"""P4-5 보유 자료(고객 제공 수치) 업로드: 양식 → 올리기 → 배치 채택 → 차트·계산에 쓰임."""
import io
import zipfile
from datetime import date

from app.db import SessionLocal
from app.models import Project
from app.services.inputs import load_inputs
from core.ingestion.csv_import import CLIENT_METHOD, client_charts, client_template_csv, import_client_csv, xlsx_to_csv
from core.schemas.project import Project as CoreProject
from tests.integration.test_owned_compare import ok, sample_project

HEAD = "대상,지표,값,단위,시작일,종료일,구분,응답자 수,출처,출처 날짜\n"
ROWS = ("브랜드A,브랜드 인지율,42.5,%,2026-01-01,2026-06-30,20대,500,2026 브랜드 트래커,2026-07-10\n"
        "경쟁X,브랜드 인지율,55,%,2026-01-01,2026-06-30,20대,500,2026 브랜드 트래커,2026-07-10\n"
        "브랜드A,월 매출,3,억원,2026-01,2026-01,,,내부 리포트,\n"
        "브랜드A,월 매출,4,억원,2026-02,2026-02,,,내부 리포트,\n"
        "없는브랜드,브랜드 인지율,10,%,2026-01-01,2026-06-30,,,트래커,\n"
        "브랜드A,브랜드 인지율,abc,%,2026-01-01,2026-06-30,,,트래커,\n")


def _core() -> CoreProject:
    return CoreProject.model_validate({
        "name": "p", "client": "c", "period": {"start": "2026-01-01", "end": "2026-09-30"},
        "brands": [{"id": "B1", "name": "브랜드A", "competitors": ["경쟁X"]}], "enabled_slides": ["cover"]})


def _xlsx(rows: list[list[str]]) -> bytes:
    """openpyxl 없이 만든 최소 xlsx(인라인 문자열 + 숫자)."""
    def cell(ci, ri, v):
        ref = f"{chr(65 + ci)}{ri}"
        try:
            float(v)
            return f'<c r="{ref}"><v>{v}</v></c>'
        except ValueError:
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    body = "".join(f'<row r="{ri}">' + "".join(cell(ci, ri, v) for ci, v in enumerate(r) if v != "") + "</row>"
                   for ri, r in enumerate(rows, 1))
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{m}" xmlns:r="{r}"><sheets><sheet name="s" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{m}"><sheetData>{body}</sheetData></worksheet>')
    return buf.getvalue()


def test_template_has_only_the_korean_header():
    t = client_template_csv()
    assert t.startswith("﻿대상,지표,값,단위,시작일,종료일,구분,응답자 수,출처,출처 날짜") and t.count("\n") == 1


def test_rows_become_candidate_facts_with_client_footnote():
    res = import_client_csv(HEAD + ROWS, _core(), "BAT-1")
    assert len(res.facts) == 4 and {e.row_no for e in res.errors} == {6, 7}
    assert {e.column for e in res.errors} == {"대상", "값"}
    f = res.facts[0]
    assert (f.entity, f.label, str(f.value), f.unit) == ("브랜드A", "브랜드 인지율", "42.5", "percent")
    assert f.source == "고객 제공 · 2026 브랜드 트래커" and f.method == CLIENT_METHOD
    assert f.dims == {"segment": "20대", "n": "500"} and f.measured_at == date(2026, 7, 10)
    assert f.verification_status == "candidate"
    sales = res.facts[2]
    assert sales.value == 300_000_000 and sales.unit == "krw"
    assert (sales.period_start, sales.period_end) == (date(2026, 1, 1), date(2026, 1, 31))


def test_english_headers_and_missing_columns():
    eng = "entity,metric_label,value,unit,period_start,period_end,source_name\n브랜드A,재구매율,31,%,2026-01-01,2026-03-31,설문\n"
    assert len(import_client_csv(eng, _core(), "B").facts) == 1
    res = import_client_csv("대상,값\n브랜드A,1\n", _core(), "B")
    assert not res.facts and {e.column for e in res.errors} >= {"지표", "출처"}


def test_xlsx_reads_like_the_csv():
    rows = [HEAD.strip().split(","), ["브랜드A", "재구매율", "0.30000000000000004", "%", "46023", "46112", "", "", "설문", ""]]
    text = xlsx_to_csv(_xlsx(rows))
    f = import_client_csv(text, _core(), "B").facts[0]
    assert str(f.value) == "0.3" and f.period_start == date(2026, 1, 1) and f.period_end == date(2026, 3, 31)


def test_charts_bar_for_one_period_line_for_many():
    facts = import_client_csv(HEAD + ROWS, _core(), "B").facts
    charts = {c["label"]: c for c in client_charts(facts, {"브랜드A"})}
    bar = charts["브랜드 인지율"]
    assert bar["kind"] == "bar_chart" and bar["segment"] == "20대" and bar["n"] == [500]
    assert [(i["entity"], i["display"], i["role"]) for i in bar["items"]] == [("브랜드A", "42.5%", "self"), ("경쟁X", "55%", "other")]
    line = charts["월 매출"]
    assert line["kind"] == "line_chart" and line["categories"] == ["2026.01", "2026.02"]
    assert [p["value"] for p in line["series"][0]["points"]] == [3e8, 4e8]


def test_upload_accept_then_chart_and_calculations(client):
    pid = sample_project(client)
    pdf = b"%PDF-1.4 fake"
    b = ok(client.post(f"/v1/projects/{pid}/imports", data={"kind": "client"},
                       files={"file": ("트래커.csv", (HEAD + ROWS).encode(), "text/csv"),
                              "source_file": ("트래커 원문.pdf", pdf, "application/pdf")}), 201)
    assert b["kind"] == "client" and b["valid_rows"] == 4 and len(b["errors"]) == 2 and b["has_source_file"]
    assert client.get(f"/v1/imports/{b['id']}/source.pdf").content == pdf

    data = ok(client.get(f"/v1/projects/{pid}/client-data"))
    assert data["charts"] == []  # 채택 전에는 차트에 나오지 않는다(자동 채택 금지)
    assert len(data["batches"][0]["rows"]) == 4
    with SessionLocal() as db:
        facts = load_inputs(db, db.get(Project, pid)).facts
        mine = [f for f in facts if f.method == CLIENT_METHOD]
        assert len(mine) == 4 and all(f.verification_status == "candidate" and f.source_id for f in mine)

    ok(client.post(f"/v1/imports/{b['id']}/review", json={"action": "accept"}))
    data = ok(client.get(f"/v1/projects/{pid}/client-data"))
    assert {c["label"] for c in data["charts"]} == {"브랜드 인지율", "월 매출"}
    by_label = {c["label"]: c for c in data["charts"]}
    assert by_label["브랜드 인지율"]["sources"] == ["고객 제공 · 2026 브랜드 트래커"]
    with SessionLocal() as db:
        facts = load_inputs(db, db.get(Project, pid)).facts
        assert all(f.verification_status == "eligible" for f in facts if f.method == CLIENT_METHOD)

    # 다른 보유 자료를 채택해도 앞 배치는 그대로(설문과 내부 리포트는 서로 다른 자료).
    b2 = ok(client.post(f"/v1/projects/{pid}/imports", data={"kind": "client"},
                        files={"file": ("설문.csv", (HEAD + "브랜드A,재구매율,31,%,2026-01,2026-03,,,설문,\n").encode(), "text/csv")}), 201)
    assert not b2["has_source_file"]
    ok(client.post(f"/v1/imports/{b2['id']}/review", json={"action": "accept"}))
    status = {x["id"]: x["status"] for x in ok(client.get(f"/v1/projects/{pid}/imports"))}
    assert status[b["id"]] == "accepted" and status[b2["id"]] == "accepted"


def test_upload_rejects_bad_files(client):
    pid = sample_project(client)
    r = client.post(f"/v1/projects/{pid}/imports", data={"kind": "client"},
                    files={"file": ("a.csv", HEAD.encode(), "text/csv"), "source_file": ("a.pdf", b"not pdf", "application/pdf")})
    assert r.status_code == 422
    r = client.post(f"/v1/projects/{pid}/imports", data={"kind": "client"},
                    files={"file": ("a.csv", "대상,값\n".encode(), "text/csv")})
    assert r.status_code == 422 and "양식" in r.text
    t = client.get("/v1/imports/client-template.csv")
    assert t.status_code == 200 and t.content.decode("utf-8-sig").startswith("대상,지표")
