from app.db import SessionLocal
from app.models import Job, new_id


def _project(client) -> dict:
    response = client.post("/v1/projects/sample")
    assert response.status_code == 201
    return response.json()


def test_health_request_id_and_metrics(client):
    live = client.get("/health/live", headers={"X-Request-ID": "req-test-123"})
    assert live.status_code == 200 and live.json() == {"ok": True}
    assert live.headers["X-Request-ID"] == "req-test-123"

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"ok": True, "checks": {"database": True, "storage": True}}

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "ptk_http_requests_total" in metrics.text
    assert 'route="/health/live"' in metrics.text


def test_invalid_request_id_is_replaced(client):
    response = client.get("/health/live", headers={"X-Request-ID": "bad request id"})
    request_id = response.headers["X-Request-ID"]
    assert request_id.startswith("req-") and request_id != "bad request id"


def test_job_list_filters_and_exposes_correlation(client):
    project = _project(client)
    with SessionLocal() as db:
        failed = Job(id=new_id("JOB"), project_id=project["id"], project_version=project["version"],
                     kind="export", state="failed", params={"_request_id": "req-job"}, result={}, usage={},
                     error_code="RENDER_FAILED", error_message="렌더 실패")
        other = Job(id=new_id("JOB"), project_id=project["id"], project_version=project["version"],
                    kind="deck_build", state="succeeded", params={}, result={}, usage={})
        db.add_all([failed, other])
        db.commit()

    response = client.get("/v1/jobs", params={"project_id": project["id"], "state": "failed", "limit": 10})
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == failed.id
    assert jobs[0]["request_id"] == "req-job"
    assert jobs[0]["error_code"] == "RENDER_FAILED"


def test_error_response_contains_request_id(client):
    response = client.get("/v1/jobs/does-not-exist", headers={"X-Request-ID": "req-error"})
    assert response.status_code == 404
    assert response.json()["error"]["request_id"] == "req-error"
