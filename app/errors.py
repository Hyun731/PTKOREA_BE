"""Structured API errors (DEVELOPMENT_PLAN 5 대표 오류 코드). Messages say what to do next;
no API keys or raw tracebacks reach the client."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, action: str = "", detail: Optional[Any] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.action, self.detail = status, code, message, action, detail


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what}을(를) 찾을 수 없습니다", "목록을 새로고침하세요")


def stale_version(current: int, latest: Any = None) -> ApiError:
    return ApiError(409, "STALE_VERSION", "다른 화면에서 먼저 수정되었습니다", "최신 내용을 확인한 뒤 다시 적용하세요",
                    {"current_version": current, "latest": latest})


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {
        "code": exc.code, "message": exc.message, "action": exc.action, "detail": jsonable_encoder(exc.detail)}})


async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    import logging
    logging.getLogger("api").exception("unhandled", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": {
        "code": "INTERNAL", "message": "처리 중 오류가 발생했습니다", "action": "잠시 후 다시 시도하세요", "detail": None}})
