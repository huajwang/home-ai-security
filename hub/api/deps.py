"""Request dependencies: auth, app services, rate limits."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hub import config
from hub.auth import decode_access_token
from hub.errors import raise_api
from hub.storage import Store

bearer = HTTPBearer(auto_error=False)


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_services(request: Request) -> dict[str, Any]:
    return {
        "store": request.app.state.store,
        "state": request.app.state.hub_state,
        "lock": request.app.state.lock,
        "bus": request.app.state.bus,
        "calls": request.app.state.calls,
        "vision": request.app.state.vision,
        "login_limiter": request.app.state.login_limiter,
        "unlock_limiter": request.app.state.unlock_limiter,
    }


def _token_from_request(
    request: Request,
    creds: HTTPAuthorizationCredentials | None,
) -> str | None:
    if creds and creds.scheme.lower() == "bearer":
        return creds.credentials
    query = request.query_params.get("access_token")
    if query:
        return query
    return None


def current_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    token = _token_from_request(request, creds)
    if not token:
        raise_api(401, "unauthorized", "Missing access token")
    try:
        payload = decode_access_token(store, token)
    except Exception:
        raise_api(401, "unauthorized", "Invalid or expired token")
    user = store.get_user(int(payload["sub"]))
    if user is None:
        raise_api(401, "unauthorized", "User no longer exists")
    device = store.get_device(int(payload["device_id"]))
    if device is None:
        raise_api(401, "unauthorized", "Device is no longer paired")
    return {
        "user": user,
        "device": device,
        "payload": payload,
    }


def require_owner(principal: dict[str, Any] = Depends(current_principal)) -> dict[str, Any]:
    if principal["user"]["role"] != "owner":
        raise_api(403, "forbidden", "Owner role required")
    return principal


def require_unlock(principal: dict[str, Any] = Depends(current_principal)) -> dict[str, Any]:
    if not bool(principal["user"]["can_unlock"]):
        raise_api(403, "forbidden", "Unlock is not allowed for this user")
    return principal


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["id"],
        "ts": event["ts"],
        "label": event["label"],
        "confidence": event["confidence"],
        "snapshot_url": f"/v1/events/{event['id']}/snapshot" if event.get("snapshot_path") else None,
        "clip_url": f"/v1/events/{event['id']}/clip" if event.get("clip_path") else None,
    }


def home_payload() -> dict[str, str]:
    return {"name": config.HOME_NAME}
