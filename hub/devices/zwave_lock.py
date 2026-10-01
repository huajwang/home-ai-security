"""Schlage deadbolt through the local Z-Wave controller on the Zooz stick."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from hub import config
from hub.devices.lock import LockResult, LockState
from hub.storage import Store


class ZwaveLockAdapter:
    name = "zwave"

    def __init__(self, store: Store) -> None:
        self._store = store
        self._state = LockState.UNKNOWN
        self._updated_at = _now()

    def get_status(self) -> str:
        try:
            body = self._request("GET", "/status", timeout=2)
            self._state = str(body.get("state") or LockState.UNKNOWN)
            self._updated_at = _now()
        except Exception:
            pass
        return self._state

    def updated_at(self) -> str:
        return self._updated_at

    def pairing(self) -> dict[str, Any]:
        try:
            body = self._request("GET", "/status", timeout=2)
        except Exception as exc:  # noqa: BLE001
            return {"pin_required": False, "error": str(exc)}
        return {
            "pin_required": bool(body.get("pin_required")),
            "including": bool(body.get("including")),
        }

    def lock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult:
        return self._act(actor, device_id, "lock", reason)

    def unlock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult:
        return self._act(actor, device_id, "unlock", reason)

    def start_inclusion(self) -> LockResult:
        try:
            body = self._request("POST", "/inclusion/start", {})
        except Exception as exc:  # noqa: BLE001
            return LockResult(False, self.get_status(), str(exc))
        self._state = str(body.get("state") or self._state)
        return LockResult(True, self._state, str(body.get("message") or "inclusion started"))

    def submit_pin(self, pin: str) -> LockResult:
        try:
            body = self._request("POST", "/inclusion/pin", {"pin": pin})
        except Exception as exc:  # noqa: BLE001
            return LockResult(False, self.get_status(), str(exc))
        return LockResult(bool(body.get("ok")), self.get_status(), str(body.get("message") or "pin sent"))

    def start_exclusion(self) -> LockResult:
        try:
            body = self._request("POST", "/exclusion/start", {})
        except Exception as exc:  # noqa: BLE001
            return LockResult(False, self.get_status(), str(exc))
        return LockResult(True, self.get_status(), str(body.get("message") or "exclusion started"))

    def _act(self, actor: str, device_id: int | None, action: str, reason: str | None) -> LockResult:
        try:
            body = self._request("POST", "/lock", {"action": action})
        except Exception as exc:  # noqa: BLE001
            result = LockResult(False, self.get_status(), str(exc))
            self._store.add_lock_audit(actor, device_id, action, "error", reason)
            return result
        self._state = str(body.get("state") or LockState.UNKNOWN)
        self._updated_at = _now()
        result = LockResult(bool(body.get("success")), self._state, str(body.get("message") or action))
        self._store.add_lock_audit(
            actor,
            device_id,
            action,
            "ok" if result.success else "error",
            reason,
        )
        return result

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 18,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            config.ZWAVE_URL.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                message = json.loads(detail).get("message", detail)
            except json.JSONDecodeError:
                message = detail or exc.reason
            raise RuntimeError(str(message)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Z-Wave controller is not running") from exc
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise RuntimeError("Z-Wave controller returned an invalid response")
        return body


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
