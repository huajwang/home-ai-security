"""System status and arm/disarm."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from hub.api.deps import current_principal, get_services

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
        },
        "hub_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


@router.get("")
def get_system(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return _system_body(services)


@router.post("/arm")
async def arm(
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
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


@router.post("/disarm")
async def disarm(
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
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
