"""In-memory hub runtime state shared by API, vision, and media."""

from __future__ import annotations

import threading
from datetime import datetime, timezone


class HubState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.armed = False
        self.alarm_active = False
        self.last_person_at: str | None = None
        self.last_confidence = 0.0
        self.vision_fps = 0.0
        self.vision_running = False
        self.vision_error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "armed": self.armed,
                "alarm_active": self.alarm_active,
                "last_person_at": self.last_person_at,
                "last_confidence": self.last_confidence,
                "vision_fps": round(self.vision_fps, 2),
                "vision_running": self.vision_running,
                "vision_error": self.vision_error,
            }

    def set_armed(self, armed: bool) -> bool:
        with self._lock:
            changed = self.armed != armed
            self.armed = armed
            if not armed:
                self.alarm_active = False
            return changed

    def mark_person(self, confidence: float) -> None:
        with self._lock:
            self.last_person_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            self.last_confidence = confidence

    def set_alarm(self, active: bool) -> bool:
        with self._lock:
            changed = self.alarm_active != active
            self.alarm_active = active
            return changed
