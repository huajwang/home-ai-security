"""Alexa Smart Home directives.

Lights can be switched. The alarm can be armed and disarmed. Alexa can lock
the bolt and can report door and lock state. Voice cannot unlock.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

_LOCK_REFUSED = "Voice assistants cannot unlock. Unlock stays on the hub and requires confirmation."
_ALARM_ID = "home-alarm"
_LOCK_ID = "home-lock"


def handle(body: dict[str, Any], home: Any) -> dict[str, Any]:
    home = _home(home)
    directive = body.get("directive")
    if not isinstance(directive, dict):
        return error("INVALID_DIRECTIVE", "That action is not available.")
    header = directive.get("header") or {}
    namespace = str(header.get("namespace") or "")
    name = str(header.get("name") or "")
    correlation = header.get("correlationToken")
    endpoint = directive.get("endpoint") or {}
    endpoint_id = str(endpoint.get("endpointId") or header.get("endpointId") or "")
    payload = directive.get("payload") if isinstance(directive.get("payload"), dict) else {}
    if namespace == "Alexa.LockController" and name == "Unlock":
        return error("INVALID_DIRECTIVE", _LOCK_REFUSED, correlation, endpoint_id or None)
    if namespace == "Alexa.LockController" and name == "Lock":
        return lock_door(home, endpoint_id, correlation)
    if namespace == "Alexa.Discovery" and name == "Discover":
        return discover(home)
    if namespace == "Alexa.Authorization" and name == "AcceptGrant":
        return {"event": {"header": _header("Alexa.Authorization", "AcceptGrant.Response"), "payload": {}}}
    if namespace == "Alexa.PowerController" and name in {"TurnOn", "TurnOff"}:
        return power(home.lights, name == "TurnOn", endpoint_id, correlation)
    if namespace == "Alexa.SecurityPanelController" and name == "Arm":
        return arm(home, endpoint_id, correlation, str(payload.get("armState") or ""))
    if namespace == "Alexa.SecurityPanelController" and name == "Disarm":
        return disarm(home, endpoint_id, correlation)
    if namespace == "Alexa" and name == "ReportState":
        return report(home, endpoint_id, correlation)
    return error("INVALID_DIRECTIVE", "That action is not available.", correlation, endpoint_id or None)


def discover(home: Any) -> dict[str, Any]:
    home = _home(home)
    rows = _rows(home.lights)
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
    endpoints.extend(_contact_endpoints(home))
    if home.state is not None:
        endpoints.append(_alarm_endpoint())
    if home.lock is not None:
        endpoints.append(_lock_endpoint())
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


def lock_door(home: Any, endpoint_id: str, correlation: Any) -> dict[str, Any]:
    home = _home(home)
    if endpoint_id not in {"", _LOCK_ID}:
        return error("NO_SUCH_ENDPOINT", "That lock is not paired.", correlation, endpoint_id)
    if home.lock is None or not hasattr(home.lock, "lock"):
        return error("INVALID_DIRECTIVE", "That action is not available.", correlation, _LOCK_ID)
    try:
        result = home.lock.lock("alexa", None, "alexa")
    except Exception as exc:  # noqa: BLE001
        return error("ENDPOINT_UNREACHABLE", str(exc) or "The lock did not respond.", correlation, _LOCK_ID)
    state = str(getattr(result, "state", "") or "").lower()
    message = str(getattr(result, "message", "") or "")
    if not getattr(result, "success", False) and state != "locked" and message != "already locked":
        return error("ENDPOINT_UNREACHABLE", message or "The lock did not respond.", correlation, _LOCK_ID)
    _tell_bus(home, {"type": "lock_changed", "state": "locked", "actor": "alexa", "action": "lock"})
    return _context_event("Response", _LOCK_ID, correlation, [_prop("Alexa.LockController", "lockState", "LOCKED")])


def arm(home: Any, endpoint_id: str, correlation: Any, arm_state: str) -> dict[str, Any]:
    home = _home(home)
    if home.state is None or not hasattr(home.state, "set_armed"):
        return error("INVALID_DIRECTIVE", "That action is not available.", correlation, endpoint_id or None)
    if endpoint_id not in {"", _ALARM_ID}:
        return error("NO_SUCH_ENDPOINT", "That alarm is not available.", correlation, endpoint_id)
    if arm_state not in {"", "ARMED_AWAY", "ARMED_STAY", "ARMED_NIGHT"}:
        return error("INVALID_DIRECTIVE", "That arm mode is not available.", correlation, _ALARM_ID)
    home.state.set_armed(True)
    _tell_bus(home, {"type": "armed_changed", "armed": True, "actor": "alexa"})
    return _context_event("Response", _ALARM_ID, correlation, [_arm_property(True)])


def disarm(home: Any, endpoint_id: str, correlation: Any) -> dict[str, Any]:
    home = _home(home)
    if home.state is None or not hasattr(home.state, "set_armed"):
        return error("INVALID_DIRECTIVE", "That action is not available.", correlation, endpoint_id or None)
    if endpoint_id not in {"", _ALARM_ID}:
        return error("NO_SUCH_ENDPOINT", "That alarm is not available.", correlation, endpoint_id)
    home.state.set_armed(False)
    _tell_bus(home, {"type": "armed_changed", "armed": False, "actor": "alexa"})
    return _context_event("Response", _ALARM_ID, correlation, [_arm_property(False)])


def report(home: Any, endpoint_id: str, correlation: Any) -> dict[str, Any]:
    home = _home(home)
    if endpoint_id == _ALARM_ID and home.state is not None:
        armed = bool(getattr(home.state, "armed", False))
        return _context_event("StateReport", _ALARM_ID, correlation, [_arm_property(armed)])
    if endpoint_id == _LOCK_ID and home.lock is not None:
        return _lock_report(home.lock, correlation)
    contact = _contact(home, endpoint_id)
    if contact is not None:
        opened = contact.get("open")
        if opened is None:
            return error("ENDPOINT_UNREACHABLE", "Waiting for the sensor.", correlation, endpoint_id)
        return _context_event(
            "StateReport",
            endpoint_id,
            correlation,
            [_prop("Alexa.ContactSensor", "detectionState", "DETECTED" if opened else "NOT_DETECTED")],
        )
    if not endpoint_id or not _known(home.lights, endpoint_id):
        return error("NO_SUCH_ENDPOINT", "That device is not paired.", correlation, endpoint_id or None)
    turned_on = bool(home.lights.is_on()) if hasattr(home.lights, "is_on") else False
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


def _home(home: Any) -> Any:
    if hasattr(home, "lights") or hasattr(home, "state") or hasattr(home, "lock") or hasattr(home, "doors"):
        if not hasattr(home, "lights"):
            home.lights = None
        return home
    return SimpleNamespace(lights=home, doors=None, lock=None, state=None, bus=None)


def _contact_endpoints(home: Any) -> list[dict[str, Any]]:
    found = []
    for contact in _contacts(home):
        ieee = str(contact.get("ieee") or "")
        name = _spoken_name(str(contact.get("name") or "")) or "Door"
        if not ieee:
            continue
        found.append(
            {
                "endpointId": ieee,
                "manufacturerName": "Home AI",
                "friendlyName": name,
                "description": "Door sensor",
                "displayCategories": ["CONTACT_SENSOR"],
                "cookie": {},
                "capabilities": [
                    {"type": "AlexaInterface", "interface": "Alexa", "version": "3"},
                    {
                        "type": "AlexaInterface",
                        "interface": "Alexa.ContactSensor",
                        "version": "3",
                        "properties": {
                            "supported": [{"name": "detectionState"}],
                            "proactivelyReported": False,
                            "retrievable": True,
                        },
                    },
                ],
            }
        )
    return found


def _alarm_endpoint() -> dict[str, Any]:
    return {
        "endpointId": _ALARM_ID,
        "manufacturerName": "Home AI",
        "friendlyName": "Alarm",
        "description": "Home alarm",
        "displayCategories": ["SECURITY_PANEL"],
        "cookie": {},
        "capabilities": [
            {"type": "AlexaInterface", "interface": "Alexa", "version": "3"},
            {
                "type": "AlexaInterface",
                "interface": "Alexa.SecurityPanelController",
                "version": "3",
                "properties": {
                    "supported": [{"name": "armState"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
                "configuration": {
                    "supportedArmStates": [{"value": "ARMED_AWAY"}, {"value": "DISARMED"}],
                },
            },
        ],
    }


def _lock_endpoint() -> dict[str, Any]:
    return {
        "endpointId": _LOCK_ID,
        "manufacturerName": "Home AI",
        "friendlyName": "Front door lock",
        "description": "Door lock",
        "displayCategories": ["SMARTLOCK"],
        "cookie": {},
        "capabilities": [
            {"type": "AlexaInterface", "interface": "Alexa", "version": "3"},
            {
                "type": "AlexaInterface",
                "interface": "Alexa.LockController",
                "version": "3",
                "properties": {
                    "supported": [{"name": "lockState"}],
                    "proactivelyReported": False,
                    "retrievable": True,
                },
            },
        ],
    }


def _contacts(home: Any) -> list[dict[str, Any]]:
    doors = getattr(home, "doors", None)
    if doors is None or not hasattr(doors, "status"):
        return []
    try:
        body = doors.status()
    except Exception:  # noqa: BLE001
        return []
    rows = body.get("contacts", []) if isinstance(body, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _contact(home: Any, endpoint_id: str) -> dict[str, Any] | None:
    for row in _contacts(home):
        if str(row.get("ieee") or "").lower() == endpoint_id.lower():
            return row
    return None


def _lock_report(lock: Any, correlation: Any) -> dict[str, Any]:
    raw = str(lock.get_status() if hasattr(lock, "get_status") else "unknown").lower()
    states = {"locked": "LOCKED", "unlocked": "UNLOCKED"}
    if raw not in states:
        return error("ENDPOINT_UNREACHABLE", "The lock has not reported yet.", correlation, _LOCK_ID)
    return _context_event(
        "StateReport",
        _LOCK_ID,
        correlation,
        [_prop("Alexa.LockController", "lockState", states[raw])],
    )


def _arm_property(armed: bool) -> dict[str, Any]:
    return _prop("Alexa.SecurityPanelController", "armState", "ARMED_AWAY" if armed else "DISARMED")


def _prop(namespace: str, name: str, value: str) -> dict[str, Any]:
    return {
        "namespace": namespace,
        "name": name,
        "value": value,
        "timeOfSample": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uncertaintyInMilliseconds": 0,
    }


def _context_event(name: str, endpoint_id: str, correlation: Any, properties: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "context": {"properties": properties},
        "event": {
            "header": _header("Alexa", name, correlation),
            "endpoint": {"endpointId": endpoint_id},
            "payload": {},
        },
    }


def _tell_bus(home: Any, payload: dict[str, Any]) -> None:
    bus = getattr(home, "bus", None)
    publish = getattr(bus, "publish_threadsafe", None)
    if publish is None:
        return
    try:
        publish(payload)
    except Exception:  # noqa: BLE001
        return


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
    if lights is None or not hasattr(lights, "list_lights"):
        return []
    found = list(lights.list_lights())
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

