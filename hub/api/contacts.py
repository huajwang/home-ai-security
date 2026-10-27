"""Zigbee door and window contact routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from hub.api.deps import current_principal, get_services

router = APIRouter(prefix="/v1/contacts", tags=["contacts"])


def contacts_body(services: dict[str, Any]) -> dict[str, Any]:
    doors = services.get("doors")
    if doors is None or not hasattr(doors, "status"):
        return {"contacts": []}
    try:
        body = doors.status()
    except Exception:  # noqa: BLE001
        return {"contacts": []}
    contacts = body.get("contacts", []) if isinstance(body, dict) else []
    return {"contacts": contacts}


@router.get("")
def list_contacts(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return contacts_body(services)
