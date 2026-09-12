"""Doorway event history and snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from hub.api.deps import current_principal, event_payload, get_services
from hub.auth import decode_access_token
from hub.errors import raise_api

router = APIRouter(tags=["events"])


@router.get("/v1/events")
def list_events(
    since: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    rows = services["store"].list_events(since, limit)
    return {"events": [event_payload(row) for row in rows]}


@router.get("/v1/events/{event_id}")
def get_event(
    event_id: int,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    row = services["store"].get_event(event_id)
    if row is None:
        raise_api(404, "not_found", "Event not found")
    return event_payload(row)


@router.get("/v1/events/{event_id}/snapshot")
def get_snapshot(
    event_id: int,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> FileResponse:
    row = services["store"].get_event(event_id)
    if row is None or not row.get("snapshot_path"):
        raise_api(404, "not_found", "Snapshot not found")
    path = Path(row["snapshot_path"])
    if not path.is_file():
        raise_api(404, "not_found", "Snapshot file missing")
    return FileResponse(path, media_type="image/jpeg")


@router.websocket("/v1/stream/events")
async def event_stream(ws: WebSocket) -> None:
    token = ws.query_params.get("access_token") or _bearer_from_headers(ws)
    if not token:
        await ws.close(code=4401)
        return
    try:
        decode_access_token(ws.app.state.store, token)
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    bus = ws.app.state.bus
    await bus.register(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unregister(ws)


def _bearer_from_headers(ws: WebSocket) -> str | None:
    header = ws.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None
