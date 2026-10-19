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
    "anyone": "person",
    "anybody": "person",
    "people": "person",
    "visitor": "person",
    "visitors": "person",
    "guest": "person",
    "guests": "person",
    "who": "person",
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
    "who", "did", "does", "do", "has", "have", "had", "come", "came", "coming", "by",
    "here", "around", "stop", "stopped", "wearing", "wear", "wore", "with", "without",
    "face", "covered", "covering", "masks", "mask", "masked", "unmasked",
}

# Longer phrases first. Bare "night" and "morning" stay exact-string aliases below.
_TIME_PHRASES = (
    ("昨天晚上", "last_night"),
    ("昨晚", "last_night"),
    ("last night", "last_night"),
    ("yesterday", "yesterday"),
    ("last day", "yesterday"),
    ("昨天", "yesterday"),
    ("this morning", "this_morning"),
    ("今天早上", "this_morning"),
    ("今早", "this_morning"),
    ("早上", "this_morning"),
    ("上午", "this_morning"),
    ("this afternoon", "this_afternoon"),
    ("今天下午", "this_afternoon"),
    ("下午", "this_afternoon"),
    ("past week", "past_week"),
    ("this week", "past_week"),
    ("最近一周", "past_week"),
    ("这周", "past_week"),
    ("本周", "past_week"),
    ("today", "today"),
    ("今天", "today"),
    ("刚才", "today"),
    ("刚刚", "today"),
)
_EXACT_TIME = {
    "yesterday": "yesterday",
    "last day": "yesterday",
    "last night": "last_night",
    "night": "last_night",
    "this morning": "this_morning",
    "morning": "this_morning",
    "this afternoon": "this_afternoon",
    "afternoon": "this_afternoon",
    "this week": "past_week",
    "past week": "past_week",
    "today": "today",
}


@dataclass(frozen=True)
class EventQuery:
    label: str | None
    camera: str | None
    start: str | None
    end: str | None
    understood: bool
    mask_detected: bool | None = None

    def as_dict(self) -> dict[str, str | None | bool]:
        return {
            "label": self.label,
            "camera": self.camera,
            "start": self.start,
            "end": self.end,
            "mask_detected": self.mask_detected,
            "understood": self.understood,
        }


def detect_timeframe(text: str) -> str | None:
    """Return a timeframe name when the text names one. None when it does not."""
    folded = " ".join(text.lower().replace("_", " ").split())
    if folded in _EXACT_TIME:
        return _EXACT_TIME[folded]
    for phrase, name in _TIME_PHRASES:
        if phrase in folded:
            return name
    return None


def timeframe_bounds(text: str, moment: datetime) -> tuple[datetime, datetime, str]:
    """Start, end, and spoken label for a timeframe mention. Defaults to today."""
    name = detect_timeframe(text) or "today"
    if name == "yesterday":
        day = moment - timedelta(days=1)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1), "yesterday"
    if name == "last_night":
        day = moment - timedelta(days=1) if moment.hour < 12 else moment
        start = day.replace(hour=21, minute=0, second=0, microsecond=0)
        end = day.replace(hour=23, minute=59, second=59, microsecond=0)
        return start, end, "last night"
    if name == "this_morning":
        start = moment.replace(hour=5, minute=0, second=0, microsecond=0)
        end = moment.replace(hour=12, minute=0, second=0, microsecond=0)
        return start, end, "this morning"
    if name == "this_afternoon":
        start = moment.replace(hour=12, minute=0, second=0, microsecond=0)
        end = moment.replace(hour=17, minute=0, second=0, microsecond=0)
        return start, end, "this afternoon"
    if name == "past_week":
        start = (moment - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, moment, "the past 7 days"
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1), "today"


def parse_question(text: str, now: datetime | None = None) -> EventQuery:
    moment = now or datetime.now().astimezone()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    if _has_cjk(text):
        return _parse_chinese(text, moment)
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

    mask_detected: bool | None = None
    if any(w in words for w in ("masked", "mask", "masks", "covering", "balaclava")) and not any(
        w in words for w in ("unmasked", "no", "without")
    ):
        mask_detected = True
    elif any(w in words for w in ("unmasked", "bare")) or (
        "no" in words and any(w in words for w in ("mask", "masks"))
    ) or ("without" in words and any(w in words for w in ("mask", "masks"))):
        mask_detected = False

    if mask_detected is not None and label is None:
        label = "person"

    day = _day(words, moment)
    part = _first(words, {name: name for name in _PARTS})
    start, end = _window(day, part, moment)
    unknown = [
        word
        for word in words
        if word not in _FILLERS and word not in _LABELS and word not in _WEEKDAYS
    ]
    understood = not unknown and any(
        value is not None for value in (label, camera, start, mask_detected)
    )
    if not understood:
        return EventQuery(None, None, None, None, False, None)
    return EventQuery(label, camera, _iso(start), _iso(end), understood, mask_detected)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _parse_chinese(text: str, moment: datetime) -> EventQuery:
    camera = None
    if any(word in text for word in ("车道", "车库")):
        camera = "driveway"
    elif any(word in text for word in ("门口", "门外", "门铃", "前门", "门前")):
        camera = "door"

    vehicle_text = text.replace("车道", "").replace("车库", "")
    label = None
    if any(word in text for word in ("人", "谁", "访客", "客人")):
        label = "person"
    elif any(word in vehicle_text for word in ("车", "汽车")):
        label = "car"

    mask_detected: bool | None = None
    if any(word in text for word in ("没戴口罩", "没有戴口罩", "未戴口罩", "没戴面具")):
        mask_detected = False
        label = label or "person"
    elif any(word in text for word in ("口罩", "面具", "蒙面")):
        mask_detected = True
        label = label or "person"

    named_time = detect_timeframe(text)
    if label is None and camera is None and mask_detected is None and named_time is None:
        return EventQuery(None, None, None, None, False, None)
    start, end, _ = timeframe_bounds(text, moment)
    return EventQuery(label, camera, _iso(start), _iso(end), True, mask_detected)


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
