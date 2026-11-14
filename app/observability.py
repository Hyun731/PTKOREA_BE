"""Request correlation and low-cardinality Prometheus metrics."""
from __future__ import annotations

import re
import time
from contextvars import ContextVar, Token
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

_REQUEST_ID = ContextVar("request_id", default="")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

HTTP_REQUESTS = Counter(
    "ptk_http_requests_total",
    "HTTP requests completed by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "ptk_http_request_duration_seconds",
    "HTTP request duration by route.",
    ("method", "route"),
)
JOBS_STARTED = Counter(
    "ptk_jobs_started_total",
    "Jobs that entered the running state.",
    ("kind",),
)
JOBS_FINISHED = Counter(
    "ptk_jobs_finished_total",
    "Jobs completed by final state.",
    ("kind", "state"),
)
JOB_DURATION = Histogram(
    "ptk_job_duration_seconds",
    "Job execution duration by kind and final state.",
    ("kind", "state"),
)
JOBS_ACTIVE = Gauge(
    "ptk_jobs_active",
    "Jobs currently executing in this process.",
    ("kind",),
)
JOB_ATTEMPTS = Histogram(
    "ptk_job_attempts",
    "Number of attempts when a job starts.",
    ("kind",),
    buckets=(1, 2, 3, 4, 5, 10),
)


def new_request_id(given: str = "") -> str:
    return given if _SAFE_REQUEST_ID.fullmatch(given) else f"req-{uuid4().hex}"


def bind_request_id(request_id: str) -> Token:
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token) -> None:
    _REQUEST_ID.reset(token)


def current_request_id() -> str:
    return _REQUEST_ID.get()


def route_label(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if path else "unmatched"


def observe_http(method: str, route: str, status: int, duration: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(duration)


def observe_job_started(kind: str, attempts: int) -> float:
    JOBS_STARTED.labels(kind).inc()
    JOBS_ACTIVE.labels(kind).inc()
    JOB_ATTEMPTS.labels(kind).observe(attempts)
    return time.monotonic()


def observe_job_finished(kind: str, state: str, started: float) -> None:
    JOBS_ACTIVE.labels(kind).dec()
    JOBS_FINISHED.labels(kind, state).inc()
    JOB_DURATION.labels(kind, state).observe(max(0.0, time.monotonic() - started))


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
