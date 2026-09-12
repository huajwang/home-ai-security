"""Lock control-plane routes. Unlock is never exposed on the media path."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from hub.api.deps import current_principal, get_services, require_unlock
from hub.errors import raise_api

router = APIRouter(prefix="/v1/lock", tags=["lock"])


class UnlockBody(BaseModel):
    confirm: bool = False
    reason: str | None = None


def _lock_body(services: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    lock = services["lock"]
    body = {
        "state": lock.get_status(),
        "updated_at": lock.updated_at(),
        "adapter": lock.name,
    }
    if extra:
        body.update(extra)
    return body


@router.get("")
def get_lock(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return _lock_body(services)


@router.post("/lock")
async def lock_door(
    principal: dict[str, Any] = Depends(require_unlock),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    result = services["lock"].lock(principal["user"]["username"], principal["device"]["id"], "app")
    await services["bus"].publish(
        {
            "type": "lock_changed",
            "state": result.state,
            "actor": principal["user"]["username"],
            "action": "lock",
        }
    )
    if not result.success and result.message == "already locked":
        raise_api(409, "already_locked", "Door is already locked")
    return _lock_body(services)


@router.post("/unlock")
async def unlock_door(
    body: UnlockBody,
    principal: dict[str, Any] = Depends(require_unlock),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    if not body.confirm:
        raise_api(400, "confirm_required", "Unlock requires confirm=true")
    if not services["unlock_limiter"].allow(str(principal["user"]["id"])):
        raise_api(429, "rate_limited", "Too many unlock attempts")
    result = services["lock"].unlock(
        principal["user"]["username"],
        principal["device"]["id"],
        body.reason or "app",
    )
    audit = {
        "actor": principal["user"]["username"],
        "device": principal["device"]["id"],
        "ts": services["lock"].updated_at(),
        "result": result.message,
    }
    await services["bus"].publish(
        {
            "type": "lock_changed",
            "state": result.state,
            "actor": principal["user"]["username"],
            "action": "unlock",
        }
    )
    if not result.success and result.message == "already unlocked":
        raise_api(409, "already_unlocked", "Door is already unlocked")
    return _lock_body(services, {"audit": audit})


@router.get("/audit")
def lock_audit(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict[str, Any] = Depends(require_unlock),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return {"audit": services["store"].list_lock_audit(limit)}
