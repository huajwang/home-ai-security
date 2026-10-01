"""Driveway camera. Separate from the Reolink doorbell."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse

from hub.api.deps import current_principal, get_services
from hub.errors import raise_api

router = APIRouter(prefix="/v1/driveway", tags=["driveway"])


@router.get("")
def driveway_status(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    camera = services.get("driveway")
    if camera is None:
        return {"enabled": False, "name": "driveway", "ready": False, "running": False, "fps": 0, "error": None}
    return camera.status()


@router.get("/snapshot")
def driveway_snapshot(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> Response:
    camera = services.get("driveway")
    jpeg = camera.jpeg() if camera is not None else None
    if not jpeg:
        raise_api(409, "no_frame", "Driveway camera has no picture yet")
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/stream")
def driveway_stream(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> StreamingResponse:
    camera = services.get("driveway")
    if camera is None or not camera.status().get("enabled"):
        raise_api(409, "no_frame", "Driveway camera is not on")
    return StreamingResponse(
        camera.mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
