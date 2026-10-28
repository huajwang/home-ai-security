"""System status and arm/disarm."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import Response

from hub.api.contacts import contacts_body
from hub.api.deps import current_principal, get_services, reject_voice_assistant
from hub.cloudlink.settings import link_status
from hub.errors import raise_api
from hub.media.live import accept_camera_socket, push_jpeg_frames

router = APIRouter(prefix="/v1/system", tags=["system"])


def _system_body(services: dict[str, Any]) -> dict[str, Any]:
    state = services["state"].snapshot()
    lock = services["lock"]
    return {
        "armed": state["armed"],
        "alarm_active": state["alarm_active"],
        "vision": {
            "fps": state["vision_fps"],
            "running": state["vision_running"],
            "error": state["vision_error"],
            "last_person_at": state["last_person_at"],
            "last_confidence": state["last_confidence"],
        },
        "lock": {
            "state": lock.get_status(),
            "updated_at": lock.updated_at(),
            "adapter": lock.name,
            "reachable": lock.reachable() if hasattr(lock, "reachable") else "unknown",
        },
        "contacts": contacts_body(services)["contacts"],
        "link": link_status(),
        "hub_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@router.get("")
def get_system(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return _system_body(services)


@router.get("/snapshot")
def get_door_snapshot(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> Response:
    vision = services.get("vision")
    frame = vision.latest_bgr() if vision is not None else None
    if frame is None:
        raise_api(409, "no_frame", "Camera has no picture yet")
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise_api(500, "encode_error", "Failed to encode snapshot")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.websocket("/live")
async def door_live(ws: WebSocket) -> None:
    if not await accept_camera_socket(ws):
        return
    vision = getattr(ws.app.state, "vision", None)

    def frame():
        if vision is None:
            return None
        return vision.latest_bgr()

    await push_jpeg_frames(ws, frame)


@router.post("/arm")
async def arm(
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    reject_voice_assistant(principal)
    changed = services["state"].set_armed(True)
    if changed:
        await services["bus"].publish(
            {
                "type": "armed_changed",
                "armed": True,
                "actor": principal["user"]["username"],
            }
        )
    return _system_body(services)


@router.post("/ring")
async def ring(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    event = services["store"].add_event("doorbell", 1.0, None, camera="door")
    await services["bus"].publish(
        {
            "type": "doorbell_pressed",
            "event": {
                "id": event["id"],
                "ts": event["ts"],
                "label": event["label"],
                "confidence": event["confidence"],
                "snapshot_url": None,
            },
        }
    )
    return {"ok": True, "event_id": event["id"]}


@router.post("/disarm")
async def disarm(
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    reject_voice_assistant(principal)
    changed = services["state"].set_armed(False)
    if changed:
        await services["bus"].publish(
            {
                "type": "armed_changed",
                "armed": False,
                "actor": principal["user"]["username"],
            }
        )
    return _system_body(services)
