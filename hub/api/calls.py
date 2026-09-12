"""WebRTC signaling over HTTPS. Media itself is DTLS-SRTP."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hub.api.deps import current_principal, get_services
from hub.errors import raise_api

router = APIRouter(prefix="/v1/calls", tags=["calls"])


class SdpBody(BaseModel):
    sdp: str
    type: str = "offer"


class IceBody(BaseModel):
    candidate: str
    sdpMid: str | None = None
    sdpMLineIndex: int | None = None


@router.post("")
async def create_call(
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, str]:
    session = services["calls"].create(int(principal["user"]["id"]))
    return {"call_id": session.id}


@router.post("/{call_id}/offer")
async def post_offer(
    call_id: str,
    body: SdpBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, str]:
    if services["calls"].get(call_id) is None:
        raise_api(404, "not_found", "Call not found")
    try:
        answer = await services["calls"].handle_offer(call_id, body.sdp, body.type or "offer")
    except Exception as exc:  # noqa: BLE001
        raise_api(400, "webrtc_error", str(exc))
    return answer


@router.post("/{call_id}/answer")
async def post_answer(
    call_id: str,
    body: SdpBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, bool]:
    if services["calls"].get(call_id) is None:
        raise_api(404, "not_found", "Call not found")
    try:
        await services["calls"].handle_answer(call_id, body.sdp, body.type or "answer")
    except Exception as exc:  # noqa: BLE001
        raise_api(400, "webrtc_error", str(exc))
    return {"ok": True}


@router.post("/{call_id}/ice")
async def post_ice(
    call_id: str,
    body: IceBody,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, bool]:
    if services["calls"].get(call_id) is None:
        raise_api(404, "not_found", "Call not found")
    try:
        await services["calls"].add_ice(call_id, body.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise_api(400, "webrtc_error", str(exc))
    return {"ok": True}


@router.delete("/{call_id}")
async def hangup(
    call_id: str,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, bool]:
    await services["calls"].hangup(call_id)
    return {"ok": True}
