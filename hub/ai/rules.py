"""Rule catalog for the home assistant.

These rules run before the on-device model. A hit means code executes the tool.
The model only sees whatever is left.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from hub.search.query import detect_timeframe


@dataclass(frozen=True)
class RuleHit:
    tool: str
    turn_on: Optional[bool] = None
    armed: Optional[bool] = None
    timeframe: Optional[str] = None
    kind: Optional[str] = None


_UNLOCK_EN = re.compile(r"\b(unlock|open)\b", re.IGNORECASE)
_UNLOCK_WITH_DOOR = re.compile(
    r"\b(unlock|open)\b.*\b(door|deadbolt|lock)\b", re.IGNORECASE
)
_STATUS_EN = re.compile(
    r"\b(is|are|check|what|tell me if)\b.*\b(armed|disarmed|locked|unlocked)\b"
    r"|\b(armed|disarmed|locked|unlocked)\b.*\b(or not|\?)",
    re.IGNORECASE,
)
_LIGHT_STATE_EN = re.compile(
    r"\b(is|are)\b.*\b(lights?|lamp|porch)\b.*\b(on|off)\b",
    re.IGNORECASE,
)
_LIGHT_COMMAND_EN = re.compile(
    r"\b(turn|switch)\s+(on|off)\b.*\b(lights?|bulbs?|porch|lamp|door)\b"
    r"|\b(lights?|bulbs?|porch|lamp)\b.*\b(on|off)\b",
    re.IGNORECASE,
)
_DISARM_EN = re.compile(r"\bdisarm(?:ed|ing)?\b", re.IGNORECASE)
_ARM_EN = re.compile(r"\barm(?:ed|ing)?\b", re.IGNORECASE)

_SEARCH_EN = (
    re.compile(
        r"\bwho\s+(came|was|is|were|stopped|visited|dropped|showed|has been|have been)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwho'?s\b.{0,24}\b(at|been|here|there|home|door|driveway)\b", re.IGNORECASE),
    re.compile(r"\bwho\b.{0,24}\b(door|driveway|here|home|house)\b", re.IGNORECASE),
    re.compile(
        r"\b(did|does|do|has|have|had|was|were|is)\s+(there\s+)?(any\s+)?"
        r"(one|body|someone|somebody|anyone|anybody|people)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(anyone|anybody|someone|somebody)\b.{0,40}\b"
        r"(come|came|coming|stop|stopped|show|showed|visit|visited|drop|dropped|"
        r"swing|swung|been|here|around|by|home)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(come|came|coming|stop|stopped|drop|dropped|swing|swung|show|showed)\s+by\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(any|recent|no)\s+(visitors?|guests?|people|cars?|vehicles?|packages?|deliveries|activity|events?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(visitors?|guests?)\b", re.IGNORECASE),
    re.compile(
        r"\b(seen|see|notice|noticed)\s+(anyone|anybody|someone|somebody|people)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(at the door|in the driveway|front door|doorbell)\b", re.IGNORECASE),
    re.compile(r"\b(find|search|show)\s+(me\s+)?(the\s+)?events?\b", re.IGNORECASE),
    re.compile(
        r"\b(package|delivery)\b.{0,24}\b(arrive|arrived|come|came|today|yesterday)\b",
        re.IGNORECASE,
    ),
)

# Substrings. Lights, arming, and briefing are matched first, so these can be short.
_SEARCH_ZH = (
    "有没有人",
    "有没人",
    "有人来",
    "有人吗",
    "有人没",
    "有人经过",
    "有人出现",
    "有人到",
    "谁来",
    "谁到",
    "谁经过",
    "有谁来",
    "有谁到",
    "来过吗",
    "来了吗",
    "来过人",
    "来过没",
    "来没来",
    "来过没有",
    "访客",
    "客人",
    "有没有车",
    "有车来",
    "有车吗",
    "车来过",
    "车道有",
    "门口有",
    "门外有",
    "门前有",
    "门铃响",
    "查事件",
    "查一下监控",
    "看监控",
    "最近有谁",
    "今天有谁",
    "昨天有谁",
)

_STATUS_PHRASES = (
    "status",
    "is the door locked",
    "is the front door locked",
    "is it locked",
    "check the lock",
    "check system",
    "system status",
    "how is the system",
    "锁了吗",
    "锁上了吗",
    "锁好了吗",
    "门锁",
    "门开了吗",
    "开门了吗",
    "什么状态",
    "系统状态",
    "布防了吗",
    "撤防了吗",
    "灯开着吗",
    "灯关了吗",
    "灯亮吗",
)

_BRIEFING_PHRASES = (
    "briefing",
    "security briefing",
    "what happened",
    "anything happen",
    "security report",
    "daily report",
    "summary of events",
    "give me a briefing",
    "catch me up",
    "简报",
    "汇报",
    "汇总",
    "总结一下",
    "什么情况",
    "有什么情况",
    "发生了什么",
    "今日概况",
    "安全报告",
)

_LIGHT_OFF_ZH = ("关灯", "灯关", "关一下灯", "关掉灯", "关闭灯", "把灯关")
_LIGHT_ON_ZH = ("开灯", "灯开", "开一下灯", "打开灯", "把灯开")
_UNLOCK_ZH = ("开锁", "解锁", "开门", "打开门", "把门打开")
_DISARM_ZH = ("撤防", "解除布防", "取消布防", "解除警报")
_ARM_ZH = ("布防", "设防")


def match_rule(text: str) -> Optional[RuleHit]:
    """Return the first matching rule, or None when the model should look at the text."""
    raw = text.strip()
    lower = raw.lower()
    if not raw:
        return None
    if _is_unlock(lower, raw):
        return RuleHit("guardrail_unlock_blocked")
    meeting = _meeting_command(lower, raw)
    if meeting == "start":
        return RuleHit("start_meeting")
    if meeting == "end":
        return RuleHit("end_meeting")
    note = _note_command(lower, raw)
    if note == "end":
        return RuleHit("end_note")
    if note == "start":
        return RuleHit("start_note")
    if note == "save":
        return RuleHit("save_note")
    task = _task_command(lower, raw)
    if task is not None:
        tool, kind = task
        return RuleHit(tool, kind=kind or None)
    if _is_status(lower, raw):
        return RuleHit("device_status")
    lights = _light_command(lower, raw)
    if lights is not None:
        return RuleHit("control_light", turn_on=lights)
    armed = _arm_command(lower, raw)
    if armed is not None:
        return RuleHit("arm_system", armed=armed)
    if _is_briefing(lower, raw):
        return RuleHit("security_briefing", timeframe=detect_timeframe(raw) or "today")
    if _is_search(lower, raw):
        return RuleHit("search_events")
    return None


_MEETING_START_EN = re.compile(r"\b(start|begin)(?:\s+the)?\s+meeting\b", re.IGNORECASE)
_MEETING_END_EN = re.compile(r"\b(end|stop|finish)(?:\s+the)?\s+meeting\b", re.IGNORECASE)
_MEETING_START_ZH = ("开始开会", "开始会议")
_MEETING_END_ZH = ("结束开会", "结束会议")


def _meeting_command(lower: str, raw: str) -> Optional[str]:
    if any(phrase in raw for phrase in _MEETING_END_ZH) or _MEETING_END_EN.search(lower):
        return "end"
    if any(phrase in raw for phrase in _MEETING_START_ZH) or _MEETING_START_EN.search(lower):
        return "start"
    return None


_NOTE_END_EN = re.compile(r"\b(end|stop) the note\b", re.IGNORECASE)
_NOTE_START_EN = re.compile(r"\bstart a note\b", re.IGNORECASE)
_NOTE_SAVE_EN = re.compile(r"\b(make|take) a note\b|\bnote that\b", re.IGNORECASE)
_READ_LIST_EN = re.compile(
    r"\bwhat(?:'s| is) on (?:my |the )?(?:shopping )?list\b|\bread (?:me )?the list\b",
    re.IGNORECASE,
)
_SHOPPING_EN = re.compile(r"\bshopping list\b", re.IGNORECASE)
_MAINTENANCE_EN = re.compile(r"\b(log maintenance|maintenance log)\b", re.IGNORECASE)
_REMINDER_EN = re.compile(r"\bremind me\b", re.IGNORECASE)


def _note_command(lower: str, raw: str) -> Optional[str]:
    if "结束记录" in raw or _NOTE_END_EN.search(lower):
        return "end"
    if "开始记录" in raw or _NOTE_START_EN.search(lower):
        return "start"
    if any(phrase in raw for phrase in ("记下来", "记个笔记")) or _NOTE_SAVE_EN.search(lower):
        return "save"
    return None


def _task_command(lower: str, raw: str) -> Optional[tuple[str, str]]:
    if "清单上有什么" in raw or _READ_LIST_EN.search(lower):
        return ("read_tasks", "")
    if "购物清单" in raw or _SHOPPING_EN.search(lower):
        return ("add_task", "shopping")
    if "保养记录" in raw or _MAINTENANCE_EN.search(lower):
        return ("add_task", "maintenance")
    if "提醒我" in raw or _REMINDER_EN.search(lower):
        return ("add_task", "reminder")
    return None


def _is_unlock(lower: str, raw: str) -> bool:
    english = _UNLOCK_WITH_DOOR.search(lower) or _UNLOCK_EN.search(lower)
    if english and "status" not in lower and "check" not in lower and "is" not in lower:
        return True
    if "灯" in raw or any(mark in raw for mark in ("吗", "么", "状态", "是不是")):
        return False
    return any(phrase in raw for phrase in _UNLOCK_ZH)


def _is_status(lower: str, raw: str) -> bool:
    if any(phrase in lower or phrase in raw for phrase in _STATUS_PHRASES):
        return True
    if _STATUS_EN.search(lower) or _LIGHT_STATE_EN.search(lower):
        return True
    return False


def _light_command(lower: str, raw: str) -> Optional[bool]:
    if any(phrase in raw for phrase in _LIGHT_OFF_ZH):
        return False
    if any(phrase in raw for phrase in _LIGHT_ON_ZH):
        return True
    if not _LIGHT_COMMAND_EN.search(lower):
        return None
    return "on" in lower.split() or "turn on" in lower or "switch on" in lower


def _arm_command(lower: str, raw: str) -> Optional[bool]:
    if (
        _DISARM_EN.search(lower)
        or "turn off the alarm" in lower
        or "disable the alarm" in lower
        or any(phrase in raw for phrase in _DISARM_ZH)
    ):
        return False
    if (
        _ARM_EN.search(lower)
        or "set the alarm" in lower
        or "turn on the alarm" in lower
        or any(phrase in raw for phrase in _ARM_ZH)
    ):
        return True
    return None


def _is_briefing(lower: str, raw: str) -> bool:
    return any(phrase in lower or phrase in raw for phrase in _BRIEFING_PHRASES)


def _is_search(lower: str, raw: str) -> bool:
    if any(pattern.search(lower) for pattern in _SEARCH_EN):
        return True
    return any(phrase in raw for phrase in _SEARCH_ZH)
