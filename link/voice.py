"""Voice-assistant policy. Unlock, lock, arm, and disarm are never forwarded."""

from __future__ import annotations

from dataclasses import dataclass

_FORBIDDEN = {"lock.unlock", "lock.lock", "system.arm", "system.disarm"}
_ALLOWED = {
    "light.on": ("POST", "/v1/lights/on"),
    "light.off": ("POST", "/v1/lights/off"),
    "contacts": ("GET", "/v1/contacts"),
    "doorbell": ("GET", "/v1/events?limit=20"),
}
_DISABLED = "Voice assistants stay off until the relay is in the US or Canada."
_REFUSED = "Voice assistants cannot unlock, lock, arm, or disarm."


@dataclass(frozen=True)
class Decision:
    status: int
    body: dict[str, str | bool]


def decide(region: str, action: str) -> Decision:
    name = action.strip().lower()
    if name in _FORBIDDEN or name.startswith("lock.") or name.startswith("system."):
        return Decision(403, {"code": "not_allowed", "message": _REFUSED})
    if region.strip().lower() not in {"us", "ca", "canada"}:
        return Decision(503, {"code": "voice_disabled", "message": _DISABLED})
    spec = _ALLOWED.get(name)
    if spec is None:
        return Decision(404, {"code": "unknown_action", "message": "That action is not available."})
    return Decision(200, {"ok": True, "method": spec[0], "path": spec[1]})
