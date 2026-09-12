"""JSON error helpers matching the v1 API contract."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def error_body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def raise_api(status: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status, detail=error_body(code, message))


def http_error_handler(_, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = detail
    else:
        body = error_body("error", str(detail))
    return JSONResponse(status_code=exc.status_code, content=body)
