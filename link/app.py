"""Relay HTTP API: ciphertext backups, and a voice webhook that stays off in China."""

from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from link.voice import decide

_HOME_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class VoiceBody(BaseModel):
    action: str
    home: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="Home AI Cloud Link", version="0.1.0")
    backup_dir = Path(os.getenv("LINK_BACKUP_DIR", "link-data/backups"))
    keys = [item.strip() for item in os.getenv("LINK_FERNET_KEYS", "").split(",") if item.strip()]
    region = os.getenv("LINK_REGION", "cn")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"ok": "true", "region": region}

    @app.post("/v1/backups/{home_id}")
    async def put_backup(home_id: str, request: Request) -> JSONResponse:
        if not _HOME_ID.match(home_id):
            return JSONResponse({"code": "bad_home"}, status_code=400)
        if not _authorized(request.headers.get("authorization", ""), keys):
            return JSONResponse({"code": "unauthorized"}, status_code=401)
        body = await request.body()
        if not body:
            return JSONResponse({"code": "empty"}, status_code=400)
        folder = backup_dir / home_id
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = folder / f"{stamp}.bin"
        target.write_bytes(body)
        return JSONResponse({"stored": True, "bytes": len(body)})

    @app.post("/voice/command")
    def voice(body: VoiceBody) -> JSONResponse:
        decision = decide(region, body.action)
        return JSONResponse(decision.body, status_code=decision.status)

    return app


def _authorized(header: str, keys: list[str]) -> bool:
    if not keys or not header.startswith("Bearer "):
        return False
    token = header.removeprefix("Bearer ").strip()
    return any(secrets.compare_digest(token, key) for key in keys)


app = create_app()
