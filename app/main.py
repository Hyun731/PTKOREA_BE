"""FastAPI app: everything under /v1 (DEVELOPMENT_PLAN 5)."""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import jobs
from app.config import settings
from app.errors import ApiError, api_error_handler, unhandled_handler
from app.routers import decks, editor, materials, meta, projects
from app.services import deck as _deck_handlers  # noqa: F401  (registers job handlers)
from app.services import insights as _insight_handlers  # noqa: F401
from app.services import research as _research_handlers  # noqa: F401

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
    token = settings.backend_token
    if token and request.method != "OPTIONS" and request.url.path != "/healthz":
        given = request.headers.get("x-backend-token", "")
        if not hmac.compare_digest(given.encode(), token.encode()):
            return JSONResponse(status_code=401, content={"error": {
                "code": "UNAUTHORIZED", "message": "인증되지 않은 요청입니다",
                "action": "웹 화면을 통해 접속하세요", "detail": None}})
    return await call_next(request)


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, unhandled_handler)
for r in (meta.router, projects.router, materials.router, decks.router, editor.router):
    app.include_router(r, prefix="/v1")


@app.get("/healthz")
def healthz():
    return {"ok": True}
