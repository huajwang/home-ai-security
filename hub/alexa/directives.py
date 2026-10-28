"""Alexa Smart Home directives. Only light power and state are accepted."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

_REFUSED = "Voice assistants cannot unlock, lock, arm, or disarm."
_REFUSED_NAMESPACES = {"Alexa.LockController", "Alexa.SecurityPanelController"}


def handle(body: dict[str, Any], lights: Any) -> dict[str, Any]:
    directive = body.get("directive")
    if not isinstance(directive, dict):
        return error("INVALID_DIRECTIVE", "That action is not available.")
    header = directive.get("header") or {}
    namespace = str(header.get("namespace") or "")
    name = str(header.get("name") or "")
    correlation = header.get("correlationToken")
    endpoint = directive.get("endpoint") or {}
    endpoint_id = str(endpoint.get("endpointId") or header.get("endpointId") or "")
    if namespace in _REFUSED_NAMESPACES or name.lower() in {"lock", "unlock", "arm", "disarm"}:
        return error("INVALID_DIRECTIVE", _REFUSED, correlation, endpoint_id or None)
    if namespace == "Alexa.Discovery" and name == "Discover":
        return discover(lights)
    if namespace == "Alexa.Authorization" and name == "AcceptGrant":
        return {"event": {"header": _header("Alexa.Authorization", "AcceptGrant.Response"), "payload": {}}}
    if namespace == "Alexa.PowerController" and name in {"TurnOn", "TurnOff"}:
        return power(lights, name == "TurnOn", endpoint_id, correlation)
    if namespace == "Alexa" and name == "ReportState":
        return report(lights, endpoint_id, correlation)
    return error("INVALID_DIRECTIVE", "That action is not available.", correlation, endpoint_id or None)


def discover(lights: Any) -> dict[str, Any]:
    rows = _rows(lights)
    endpoints = []
    for row in rows:
        endpoints.append(
            {
                "endpointId": row["ieee"],
                "manufacturerName": "Home AI",
                "friendlyName": row["name"],
                "description": "Zigbee light",
                "displayCategories": ["LIGHT"],
                "cookie": {},
                "capabilities": [
                    {"type": "AlexaInterface", "interface": "Alexa", "version": "3"},
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa.PowerController",
                        "version": "3",
                        "properties": {
                            "supported": [{"name": "powerState"}],
                            "proactivelyReported": False,
                            "retrievable": True,
                        },
                    },
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa.EndpointHealth",
                        "version": "3",
                        "properties": {
                            "supported": [{"name": "connectivity"}],
                            "proactivelyReported": False,
                            "retrievable": True,
                        },
                    },
                ],
            }
        )
    return {
        "event": {
            "header": _header("Alexa.Discovery", "Discover.Response"),
            "payload": {"endpoints": endpoints},
        }
    }


def power(lights: Any, turn_on: bool, endpoint_id: str, correlation: Any) -> dict[str, Any]:
    if not endpoint_id:
        return error("INVALID_DIRECTIVE", "That action is not available.", correlation)
    if not _known(lights, endpoint_id):
        return error("NO_SUCH_ENDPOINT", "That light is not paired.", correlation, endpoint_id)
    try:
        lights.set_on(turn_on, endpoint_id)
    except Exception as exc:  # noqa: BLE001
        return error("ENDPOINT_UNREACHABLE", str(exc) or "The light did not respond.", correlation, endpoint_id)
    return _state_event("Response", endpoint_id, "ON" if turn_on else "OFF", correlation)


def report(lights: Any, endpoint_id: str, correlation: Any) -> dict[str, Any]:
    if not endpoint_id or not _known(lights, endpoint_id):
        return error("NO_SUCH_ENDPOINT", "That light is not paired.", correlation, endpoint_id or None)
    turned_on = bool(lights.is_on()) if hasattr(lights, "is_on") else False
    return _state_event("StateReport", endpoint_id, "ON" if turned_on else "OFF", correlation)


def bearer_token(body: dict[str, Any]) -> str:
    directive = body.get("directive")
    if not isinstance(directive, dict):
        return ""
    payload = directive.get("payload") or {}
    endpoint = directive.get("endpoint") or {}
    grantee = payload.get("grantee") if isinstance(payload, dict) else None
    for scope in (
        payload.get("scope") if isinstance(payload, dict) else None,
        endpoint.get("scope") if isinstance(endpoint, dict) else None,
        grantee if isinstance(grantee, dict) else None,
    ):
        if isinstance(scope, dict) and scope.get("token"):
            return str(scope["token"])
    return ""


def error(
    code: str,
    message: str,
    correlation: Any = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "header": _header("Alexa", "ErrorResponse", correlation),
        "payload": {"type": code, "message": message},
    }
    if endpoint_id:
        event["endpoint"] = {"endpointId": endpoint_id}
    return {"event": event}


def _rows(lights: Any) -> list[dict[str, str]]:
    found = list(lights.list_lights()) if hasattr(lights, "list_lights") else []
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in found:
        ieee = str(row.get("ieee") or "")
        if not ieee or ieee.lower() in seen:
            continue
        seen.add(ieee.lower())
        unique.append(row)
    spoken = [(_spoken_name(str(row.get("name") or "")) or "Light") for row in unique]
    counts: dict[str, int] = {}
    for name in spoken:
        counts[name] = counts.get(name, 0) + 1
    named: list[dict[str, str]] = []
    for row, name in zip(unique, spoken):
        ieee = str(row.get("ieee") or "")
        if counts.get(name, 0) > 1:
            name = f"{name} {ieee.replace(':', '')[-4:]}"
        named.append({"ieee": ieee, "name": name or "Light"})
    return named


def _spoken_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in " '" else " " for ch in name)
    return " ".join(cleaned.split())


def _known(lights: Any, endpoint_id: str) -> bool:
    return any(row["ieee"].lower() == endpoint_id.lower() for row in _rows(lights))


def _state_event(name: str, endpoint_id: str, power_state: str, correlation: Any) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "context": {
            "properties": [
                {
                    "namespace": "Alexa.PowerController",
                    "name": "powerState",
                    "value": power_state,
                    "timeOfSample": stamp,
                    "uncertaintyInMilliseconds": 1500,
                },
                {
                    "namespace": "Alexa.EndpointHealth",
                    "name": "connectivity",
                    "value": {"value": "OK"},
                    "timeOfSample": stamp,
                    "uncertaintyInMilliseconds": 0,
                },
            ]
        },
        "event": {
            "header": _header("Alexa", name, correlation),
            "endpoint": {"endpointId": endpoint_id},
            "payload": {},
        },
    }


def _header(namespace: str, name: str, correlation: Any = None) -> dict[str, str]:
    header = {
        "namespace": namespace,
        "name": name,
        "payloadVersion": "3",
        "messageId": str(uuid.uuid4()),
    }
    if correlation:
        header["correlationToken"] = str(correlation)
    return header

