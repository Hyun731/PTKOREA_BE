"""FastAPI app: everything under /v1 (DEVELOPMENT_PLAN 5)."""
from __future__ import annotations

import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import jobs
from app.config import settings
from app.db import SessionLocal
from app.errors import ApiError, api_error_handler, unhandled_handler
from app.observability import (bind_request_id, metrics_response, new_request_id, observe_http, reset_request_id,
                               route_label)
from app.routers import decks, diagnosis, editor, materials, meta, projects, summary
from app.services import deck as _deck_handlers  # noqa: F401  (registers job handlers)
from app.services import insights as _insight_handlers  # noqa: F401
from app.services import case_commentary as _case_commentary_handlers  # noqa: F401
from app.services import research as _research_handlers  # noqa: F401
from app.services import lazy_extract as _lazy_extract_handlers  # noqa: F401

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url.startswith("sqlite"):
        # Dev/test: same migrations as production. Postgres runs `alembic upgrade head` explicitly.
        from app.migrate import upgrade_to_head

        upgrade_to_head()
    n = jobs.recover_orphans()
    if n:
        logging.getLogger("api").warning("marked %d orphaned jobs as failed", n)
    yield


app = FastAPI(title="PTK Research Deck API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_backend_token(request: Request, call_next):
    request_id = new_request_id(request.headers.get("x-request-id", ""))
    request.state.request_id = request_id
    context_token = bind_request_id(request_id)
    started = time.monotonic()
    response = None
    try:
        token = settings.backend_token
        public = {"/healthz", "/health/live", "/health/ready"}
        if token and request.method != "OPTIONS" and request.url.path not in public:
            given = request.headers.get("x-backend-token", "")
            authorization = request.headers.get("authorization", "")
            if authorization.startswith("Bearer "):
                given = authorization.removeprefix("Bearer ")
            if not hmac.compare_digest(given.encode(), token.encode()):
                response = JSONResponse(status_code=401, content={"error": {
                    "code": "UNAUTHORIZED", "message": "인증되지 않은 요청입니다",
                    "action": "웹 화면을 통해 접속하세요", "detail": None, "request_id": request_id}})
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        observe_http(request.method, route_label(request.scope), response.status_code if response else 500,
                     time.monotonic() - started)
        reset_request_id(context_token)


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, unhandled_handler)
for r in (meta.router, projects.router, materials.router, decks.router, editor.router, summary.router,
          diagnosis.router):
    app.include_router(r, prefix="/v1")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/health/live")
def health_live():
    return {"ok": True}


@app.get("/health/ready")
def health_ready():
    checks = {"database": False, "storage": False}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
        settings.storage_root.mkdir(parents=True, exist_ok=True)
        checks["storage"] = settings.storage_root.is_dir() and os.access(settings.storage_root, os.W_OK)
    except Exception:
        logging.getLogger("health").exception("readiness check failed")
    status = 200 if all(checks.values()) else 503
    return JSONResponse(status_code=status, content={"ok": status == 200, "checks": checks})


@app.get("/metrics")
def metrics():
    return metrics_response()
