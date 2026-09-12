"""Auth and device pairing routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hub.api.deps import current_principal, get_services, home_payload, require_owner
from hub.auth import (
    hash_token,
    issue_access_token,
    issue_refresh_token,
    public_user,
    refresh_is_valid,
    verify_password,
)
from hub.errors import raise_api

router = APIRouter(prefix="/v1", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str
    device_name: str = Field(min_length=1, max_length=80)
    device_role: Literal["phone", "station"]


class RefreshBody(BaseModel):
    refresh_token: str


class LogoutBody(BaseModel):
    refresh_token: str | None = None


@router.post("/auth/login")
def login(body: LoginBody, services: dict[str, Any] = Depends(get_services)) -> dict[str, Any]:
    limiter = services["login_limiter"]
    if not limiter.allow(body.username.lower()):
        raise_api(429, "rate_limited", "Too many login attempts")
    store = services["store"]
    user = store.get_user_by_name(body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise_api(401, "unauthorized", "Invalid username or password")
    device = store.create_device(user["id"], body.device_name, body.device_role)
    access = issue_access_token(store, user, device)
    refresh = issue_refresh_token(store, user["id"], device["id"])
    return {
        "access_token": access,
        "refresh_token": refresh,
        "user": public_user(user),
        "home": home_payload(),
        "device": {
            "id": device["id"],
            "device_name": device["device_name"],
            "device_role": device["device_role"],
        },
    }


@router.post("/auth/refresh")
def refresh(body: RefreshBody, services: dict[str, Any] = Depends(get_services)) -> dict[str, Any]:
    store = services["store"]
    row = store.get_refresh(hash_token(body.refresh_token))
    if not refresh_is_valid(row):
        raise_api(401, "unauthorized", "Invalid or expired refresh token")
    user = store.get_user(int(row["user_id"]))
    device = store.get_device(int(row["device_id"]))
    if user is None or device is None:
        raise_api(401, "unauthorized", "Session is no longer valid")
    store.revoke_refresh(hash_token(body.refresh_token))
    access = issue_access_token(store, user, device)
    new_refresh = issue_refresh_token(store, user["id"], device["id"])
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "user": public_user(user),
        "home": home_payload(),
    }


@router.post("/auth/logout")
def logout(
    body: LogoutBody,
    principal: dict[str, Any] = Depends(current_principal),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, bool]:
    store = services["store"]
    if body.refresh_token:
        store.revoke_refresh(hash_token(body.refresh_token))
    store.revoke_device_refresh(int(principal["device"]["id"]))
    return {"ok": True}


@router.get("/me")
def me(principal: dict[str, Any] = Depends(current_principal)) -> dict[str, Any]:
    return {
        "user": public_user(principal["user"]),
        "device": {
            "id": principal["device"]["id"],
            "device_name": principal["device"]["device_name"],
            "device_role": principal["device"]["device_role"],
        },
        "home": home_payload(),
    }


@router.get("/devices")
def list_devices(
    _: dict[str, Any] = Depends(require_owner),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, Any]:
    return {"devices": services["store"].list_devices()}


@router.delete("/devices/{device_id}")
def delete_device(
    device_id: int,
    _: dict[str, Any] = Depends(require_owner),
    services: dict[str, Any] = Depends(get_services),
) -> dict[str, bool]:
    if not services["store"].delete_device(device_id):
        raise_api(404, "not_found", "Device not found")
    return {"ok": True}
