"""One stored event per visit for labels that do not raise the door alarm."""

from __future__ import annotations

from hub import config


class ObjectVisits:
    def __init__(self) -> None:
        self._streak: dict[str, int] = {}
        self._open: set[str] = set()
        self._last: dict[str, float] = {}

    def update(self, seen: dict[str, float], now: float) -> list[tuple[str, float]]:
        ready: list[tuple[str, float]] = []
        for label in list(self._streak):
            if label not in seen:
                self._streak[label] = 0
                self._open.discard(label)
        for label, confidence in seen.items():
            self._streak[label] = self._streak.get(label, 0) + 1
            if self._streak[label] < config.FRAMES_REQUIRED_FOR_ALERT or label in self._open:
                continue
            if now - self._last.get(label, 0.0) < config.ALARM_COOLDOWN_SECONDS:
                continue
            self._open.add(label)
            self._last[label] = now
            ready.append((label, confidence))
        return ready
