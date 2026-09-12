"""Certified-lock adapter interface plus an in-memory stub for v1."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from hub.storage import Store


class LockState:
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    UNKNOWN = "unknown"


@dataclass
class LockResult:
    success: bool
    state: str
    message: str


class LockAdapter(Protocol):
    name: str

    def get_status(self) -> str: ...

    def updated_at(self) -> str: ...

    def lock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult: ...

    def unlock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult: ...


class StubLockAdapter:
    """Always-succeeds lock used until a vendor SDK is plugged in."""

    name = "stub"

    def __init__(self, store: Store) -> None:
        self._store = store
        self._state = LockState.LOCKED
        self._updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._lock = threading.Lock()

    def get_status(self) -> str:
        with self._lock:
            return self._state

    def updated_at(self) -> str:
        with self._lock:
            return self._updated_at

    def _set(self, state: str) -> None:
        self._state = state
        self._updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def lock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult:
        with self._lock:
            if self._state == LockState.LOCKED:
                result = LockResult(False, self._state, "already locked")
            else:
                self._set(LockState.LOCKED)
                result = LockResult(True, self._state, "locked")
        self._store.add_lock_audit(actor, device_id, "lock", "ok" if result.success else "noop", reason)
        return result

    def unlock(self, actor: str, device_id: int | None, reason: str | None = None) -> LockResult:
        with self._lock:
            if self._state == LockState.UNLOCKED:
                result = LockResult(False, self._state, "already unlocked")
            else:
                self._set(LockState.UNLOCKED)
                result = LockResult(True, self._state, "unlocked")
        self._store.add_lock_audit(actor, device_id, "unlock", "ok" if result.success else "noop", reason)
        return result


# Later: class NukiLockAdapter:  # implements LockAdapter
# Later: class YaleLockAdapter:  # implements LockAdapter


def build_lock_adapter(store: Store) -> LockAdapter:
    """Swap this factory when a certified lock is available."""
    return StubLockAdapter(store)
