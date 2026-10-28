"""Alexa Smart Home endpoint and account-linking login."""

from __future__ import annotations

import base64
import hmac
import json
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from hub import config
from hub.alexa import directives, oauth
from hub.alexa.signature import SignatureError, verify_request
from hub.auth import (
    decode_access_token,
    issue_access_token,
    issue_refresh_token,
    refresh_is_valid,
    verify_password,
)
from hub.auth import hash_token

router = APIRouter(tags=["alexa"])


@router.post("/alexa")
async def alexa_directive(request: Request) -> JSONResponse:
    body = await request.body()
    if not _trusted_forwarder(request):
        try:
            verify_request(body, request.headers)
        except SignatureError:
            return JSONResponse({"code": "invalid_signature"}, status_code=400)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"code": "invalid_directive"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"code": "invalid_directive"}, status_code=400)
    token = directives.bearer_token(payload)
    principal = _lights_principal(request, token)
    if principal is None:
        return JSONResponse(directives.error("INVALID_AUTHORIZATION_CREDENTIAL", "Sign in to Alexa again."))
    home = SimpleNamespace(
        lights=request.app.state.lights,
        doors=getattr(request.app.state, "doors", None),
        lock=getattr(request.app.state, "lock", None),
        state=getattr(request.app.state, "hub_state", None),
        bus=getattr(request.app.state, "bus", None),
    )
    return JSONResponse(directives.handle(payload, home))


@router.get("/alexa/oauth/authorize")
def authorize_form(request: Request) -> HTMLResponse:
    client_id = request.query_params.get("client_id", "")
    redirect_uri = request.query_params.get("redirect_uri", "")
    state = request.query_params.get("state", "")
    response_type = request.query_params.get("response_type", "")
    problem = _authorize_problem(client_id, redirect_uri, state, response_type)
    if problem:
        return HTMLResponse(f"<p>{problem}</p>", status_code=400)
    return HTMLResponse(oauth.login_page(client_id, redirect_uri, state))


@router.post("/alexa/oauth/authorize", response_model=None)
async def authorize_submit(request: Request) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    state = str(form.get("state") or "")
    response_type = str(form.get("response_type") or "")
    problem = _authorize_problem(client_id, redirect_uri, state, response_type)
    if problem:
        return HTMLResponse(f"<p>{problem}</p>", status_code=400)
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    limiter = request.app.state.login_limiter
    store = request.app.state.store
    if not limiter.allow(username.lower()):
        page = oauth.login_page(client_id, redirect_uri, state, "Too many login attempts")
        return HTMLResponse(page, status_code=429)
    user = store.get_user_by_name(username)
    if user is None or not verify_password(password, user["password_hash"]):
        page = oauth.login_page(client_id, redirect_uri, state, "Invalid username or password")
        return HTMLResponse(page, status_code=401)
    device = store.create_device(int(user["id"]), "Alexa", "alexa")
    code = oauth.save_code(request.app, int(user["id"]), int(device["id"]), redirect_uri)
    return RedirectResponse(oauth.redirect_target(redirect_uri, code, state), status_code=302)


@router.post("/alexa/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    form = await request.form()
    client_id, client_secret = _client_credentials(request, form)
    if not oauth.client_matches(client_id, client_secret):
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    grant = str(form.get("grant_type") or "")
    store = request.app.state.store
    if grant == "authorization_code":
        redirect_uri = str(form.get("redirect_uri") or "")
        row = oauth.take_code(request.app, str(form.get("code") or ""), redirect_uri)
        if row is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        user = store.get_user(int(row["user_id"]))
        device = store.get_device(int(row["device_id"]))
        if user is None or device is None or device.get("device_role") != "alexa":
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse(_token_body(store, user, device))
    if grant == "refresh_token":
        current = str(form.get("refresh_token") or "")
        saved = store.get_refresh(hash_token(current))
        if not refresh_is_valid(saved):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        user = store.get_user(int(saved["user_id"]))
        device = store.get_device(int(saved["device_id"]))
        if user is None or device is None or device.get("device_role") != "alexa":
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        store.revoke_refresh(hash_token(current))
        return JSONResponse(_token_body(store, user, device))
    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


def _trusted_forwarder(request: Request) -> bool:
    expected = config.ALEXA_FORWARD_SECRET
    presented = request.headers.get("x-home-ai-forwarder", "")
    if not expected or not presented:
        return False
    try:
        return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def _authorize_problem(client_id: str, redirect_uri: str, state: str, response_type: str) -> str:
    if not oauth.configured():
        return "Alexa linking is not configured"
    if not oauth.client_matches(client_id):
        return "Unknown Alexa client"
    if response_type != "code" or not oauth.amazon_redirect(redirect_uri) or not oauth.safe_state(state):
        return "Alexa sent an invalid link request"
    return ""


def _client_credentials(request: Request, form: Any) -> tuple[str, str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            client_id, secret = decoded.split(":", 1)
            return client_id, secret
        except (ValueError, UnicodeDecodeError):
            return "", ""
    return str(form.get("client_id") or ""), str(form.get("client_secret") or "")


def _lights_principal(request: Request, token: str) -> dict[str, Any] | None:
    if not token:
        return None
    store = request.app.state.store
    try:
        payload = decode_access_token(store, token)
    except Exception:
        return None
    if payload.get("scope") != "lights":
        return None
    user = store.get_user(int(payload["sub"]))
    device = store.get_device(int(payload["device_id"]))
    if user is None or device is None or device.get("device_role") != "alexa":
        return None
    return {"user": user, "device": device, "payload": payload}


def _token_body(store: Any, user: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    return {
        "access_token": issue_access_token(store, user, device),
        "token_type": "bearer",
        "expires_in": config.ACCESS_TOKEN_MINUTES * 60,
        "refresh_token": issue_refresh_token(store, int(user["id"]), int(device["id"])),
    }
