"""Turn a short question into a filter over stored events.

This does not look at video and does not call a language model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone


_LABELS = {
    "person": "person",
    "someone": "person",
    "somebody": "person",
    "people": "person",
    "car": "car",
    "cars": "car",
    "vehicle": "car",
    "truck": "truck",
    "bus": "bus",
    "dog": "dog",
    "cat": "cat",
    "bird": "bird",
    "bicycle": "bicycle",
    "bike": "bicycle",
    "motorbike": "motorbike",
    "motorcycle": "motorbike",
    "backpack": "backpack",
    "suitcase": "suitcase",
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_PARTS = {
    "morning": (time(5, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
    "night": (time(21, 0), time(23, 59, 59)),
}
_FILLERS = {
    "a", "an", "at", "the", "in", "on", "of", "to", "my", "me", "was", "were", "there",
    "any", "this", "show", "find", "please", "last", "yesterday", "today", "door",
    "doorbell", "front", "driveway", "morning", "afternoon", "evening", "night",
}


@dataclass(frozen=True)
class EventQuery:
    label: str | None
    camera: str | None
    start: str | None
    end: str | None
    understood: bool

    def as_dict(self) -> dict[str, str | None | bool]:
        return {
            "label": self.label,
            "camera": self.camera,
            "start": self.start,
            "end": self.end,
            "understood": self.understood,
        }


def parse_question(text: str, now: datetime | None = None) -> EventQuery:
    moment = now or datetime.now().astimezone()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    words = [word.strip(".,?!").lower() for word in text.split()]
    words = [word for word in words if word]

    label = _first(words, _LABELS)
    if "doorbell" in words and label is None:
        label = "doorbell"
    camera = None
    if "driveway" in words:
        camera = "driveway"
    elif any(word in words for word in ("door", "doorbell", "front")):
        camera = "door"

    day = _day(words, moment)
    part = _first(words, {name: name for name in _PARTS})
    start, end = _window(day, part, moment)
    unknown = [
        word
        for word in words
        if word not in _FILLERS and word not in _LABELS and word not in _WEEKDAYS
    ]
    understood = not unknown and any(value is not None for value in (label, camera, start))
    if not understood:
        return EventQuery(None, None, None, None, False)
    return EventQuery(label, camera, _iso(start), _iso(end), understood)


def _first(words: list[str], table: dict[str, str]) -> str | None:
    for word in words:
        if word in table:
            return table[word]
    return None


def _day(words: list[str], moment: datetime) -> datetime | None:
    local = moment.astimezone()
    if "yesterday" in words:
        return local - timedelta(days=1)
    if "today" in words:
        return local
    for word in words:
        if word not in _WEEKDAYS:
            continue
        delta = (local.weekday() - _WEEKDAYS[word]) % 7
        if delta == 0 and "last" in words:
            delta = 7
        return local - timedelta(days=delta)
    if any(word in words for word in _PARTS):
        return local
    return None


def _window(
    day: datetime | None, part: str | None, moment: datetime
) -> tuple[datetime | None, datetime | None]:
    del moment
    if day is None:
        return None, None
    local = day.astimezone()
    if part is None:
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    begin, finish = _PARTS[part]
    start = local.replace(hour=begin.hour, minute=begin.minute, second=0, microsecond=0)
    end = local.replace(
        hour=finish.hour, minute=finish.minute, second=finish.second, microsecond=0
    )
    return start, end


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
