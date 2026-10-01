"""Zigbee bulb routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hub.api.deps import current_principal, get_services
from hub.errors import raise_api

router = APIRouter(prefix="/v1/lights", tags=["lights"])


class LightBody(BaseModel):
    ieee: str | None = None


class PermitBody(BaseModel):
    seconds: int = Field(default=120, ge=10, le=250)


def _unavailable(exc: Exception) -> None:
    text = str(exc)
    if "not configured" in text or "No Zigbee bulb" in text:
        raise_api(409, "no_light", text)
    raise_api(502, "light_failed", text)


@router.get("")
def list_lights(
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return services["lights"].status()


@router.post("/on")
def light_on(
    body: LightBody | None = None,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    try:
        return services["lights"].set_on(True, body.ieee if body else None)
    except Exception as exc:  # noqa: BLE001
        _unavailable(exc)


@router.post("/off")
def light_off(
    body: LightBody | None = None,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    try:
        return services["lights"].set_on(False, body.ieee if body else None)
    except Exception as exc:  # noqa: BLE001
        _unavailable(exc)


@router.post("/pair")
def pair_light(
    body: PermitBody | None = None,
    _: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    seconds = body.seconds if body else 120
    try:
        return services["lights"].permit_join(seconds)
    except Exception as exc:  # noqa: BLE001
        _unavailable(exc)
