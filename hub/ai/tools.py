"""Tools and functions for the Home AI Voice Assistant.

Includes:
- Security Briefings over specified timeframes
- Natural event search
- Device status and lock inspection (unlock strictly forbidden!)
- Zigbee light control
- Arm/disarm control
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from hub.search.query import detect_timeframe, parse_question, timeframe_bounds
from hub.state import HubState
from hub.storage import Store


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_timeframe_window(
    timeframe: str, now: Optional[datetime] = None
) -> tuple[Optional[str], Optional[str], str]:
    """Parse a timeframe, including one named inside a longer sentence."""
    moment = now or datetime.now().astimezone()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    start, end, label_name = timeframe_bounds(timeframe, moment)
    return _to_utc_iso(start), _to_utc_iso(end), label_name


def get_security_briefing(
    store: Store, timeframe: str = "today", now: Optional[datetime] = None
) -> dict[str, Any]:
    """Generate a structured security briefing from recorded events."""
    start_iso, end_iso, label_name = parse_timeframe_window(timeframe, now)
    events = store.search_events(
        label=None, camera=None, start=start_iso, end=end_iso, limit=100
    )

    total_count = len(events)
    counts_by_label: dict[str, int] = {}
    counts_by_camera: dict[str, int] = {}
    last_event: Optional[dict[str, Any]] = None

    for ev in events:
        lbl = ev.get("label", "unknown")
        cam = ev.get("camera", "camera")
        counts_by_label[lbl] = counts_by_label.get(lbl, 0) + 1
        counts_by_camera[cam] = counts_by_camera.get(cam, 0) + 1
        if last_event is None:
            last_event = ev

    # Build spoken summary text
    masked_count = sum(1 for ev in events if bool(ev.get("mask_detected")))
    if total_count == 0:
        summary = f"Security briefing for {label_name}: All quiet. No events were detected."
    else:
        parts = []
        for lbl, count in sorted(counts_by_label.items(), key=lambda x: -x[1]):
            unit = f"{count} {lbl}" if count == 1 else f"{count} {lbl}s"
            parts.append(unit)
        breakdown = ", ".join(parts)

        latest_str = ""
        if last_event:
            ts_str = last_event.get("ts", "")
            cam_str = last_event.get("camera", "door")
            lbl_str = last_event.get("label", "activity")
            try:
                dt = datetime.fromisoformat(ts_str)
                time_str = dt.strftime("%I:%M %p")
                latest_str = f" Most recent activity was {lbl_str} at the {cam_str} at {time_str}."
            except Exception:
                pass

        mask_warning = (
            f" Note: {masked_count} event{'s' if masked_count > 1 else ''} involved a person wearing a mask or face covering."
            if masked_count > 0
            else ""
        )

        summary = (
            f"Security briefing for {label_name}: {total_count} total event"
            f"{'s' if total_count != 1 else ''} recorded, including {breakdown}.{latest_str}{mask_warning}"
        )

    return {
        "timeframe": label_name,
        "total_events": total_count,
        "counts_by_label": counts_by_label,
        "counts_by_camera": counts_by_camera,
        "summary": summary,
        "events": events[:10],
    }


_ZH_PERIOD = {
    "today": "今天",
    "yesterday": "昨天",
    "last_night": "昨晚",
    "this_morning": "今天早上",
    "this_afternoon": "今天下午",
    "past_week": "最近一周",
}
_EN_PERIOD = {
    "today": "today",
    "yesterday": "yesterday",
    "last_night": "last night",
    "this_morning": "this morning",
    "this_afternoon": "this afternoon",
    "past_week": "the past 7 days",
}
_ZH_PLACE = {"driveway": "车道", "door": "门口"}
_ZH_THING = {"person": "人", "car": "车", "cat": "猫", "dog": "狗"}
_EN_THING = {"person": "person", "car": "car", "cat": "cat", "dog": "dog"}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _when_phrase(ts: str, now: datetime, chinese: bool) -> str:
    moment = now.astimezone()
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(moment.tzinfo)
    clock = _clock(local)
    if local.date() == moment.date():
        return clock
    if chinese:
        return f"{local.month}月{local.day}日 {clock}"
    return f"{local.strftime('%b')} {local.day}, {clock}"


def _empty_summary(query: str, label: str | None, period: str) -> str:
    if _has_cjk(query):
        when = _ZH_PERIOD.get(period, "这个时间")
        if label == "person":
            return f"{when}没有人来过。"
        if label == "car":
            return f"{when}没有车来过。"
        return f"{when}没有记录到事件。"
    when = _EN_PERIOD.get(period, "that time")
    if label == "person":
        return f"No one came by {when}."
    if label == "car":
        return f"No car came by {when}."
    return f"No events were recorded {when}."


def _latest_sentence(event: dict[str, Any], now: datetime, chinese: bool) -> str:
    label = str(event.get("label") or "event")
    camera = str(event.get("camera") or "camera")
    when = _when_phrase(str(event.get("ts") or ""), now, chinese)
    if chinese:
        place = _ZH_PLACE.get(camera, camera)
        thing = _ZH_THING.get(label, label)
        return f"最近一次是{when}，{place}有一个{thing}。"
    thing = _EN_THING.get(label, label)
    return f"The latest was a {thing} at the {camera} at {when}."


def _found_summary(query: str, events: list[dict[str, Any]], now: datetime) -> str:
    chinese = _has_cjk(query)
    details = []
    for ev in events[:3]:
        label = str(ev.get("label") or "event")
        camera = str(ev.get("camera") or "camera")
        when = _when_phrase(str(ev.get("ts") or ""), now, chinese)
        mask = "，戴了口罩" if chinese and ev.get("mask_detected") else ""
        mask_en = " (masked)" if not chinese and ev.get("mask_detected") else ""
        if chinese:
            place = _ZH_PLACE.get(camera, camera)
            thing = _ZH_THING.get(label, label)
            details.append(f"{when} {place}有一个{thing}{mask}")
        else:
            details.append(f"{label}{mask_en} at {camera} around {when}")
    count = len(events)
    if chinese:
        return f"找到 {count} 起：" + "；".join(details) + "。"
    noun = "event" if count == 1 else "events"
    return f"Found {count} {noun}: " + "; ".join(details) + "."


def _media_item(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not event.get("snapshot_path"):
        return None
    event_id = event.get("id")
    if not event_id:
        return None
    clip = f"/v1/events/{event_id}/clip" if event.get("clip_path") else None
    return {
        "id": event_id,
        "ts": event.get("ts"),
        "label": event.get("label"),
        "camera": event.get("camera"),
        "snapshot_url": f"/v1/events/{event_id}/snapshot",
        "clip_url": clip,
    }


def _media_for(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for event in events[:3]:
        item = _media_item(event)
        if item:
            items.append(item)
    return items


def search_events_tool(
    store: Store, query: str, now: Optional[datetime] = None
) -> dict[str, Any]:
    """Search events using flexible natural question parser."""
    parsed = parse_question(query, now=now)
    events: list[dict[str, Any]] = []

    if parsed.understood:
        events = store.search_events(
            label=parsed.label,
            camera=parsed.camera,
            start=parsed.start,
            end=parsed.end,
            limit=20,
            mask_detected=parsed.mask_detected,
        )
    else:
        # Fallback keyword extraction if strict parse_question wasn't fully understood
        words = [w.strip(".,?!").lower() for w in query.split()]
        label = None
        for w in words:
            if w in (
                "person",
                "someone",
                "somebody",
                "people",
                "visitor",
                "visitors",
                "anyone",
                "anybody",
                "guest",
                "guests",
                "who",
            ):
                label = "person"
                break
            elif w in ("car", "vehicle", "truck"):
                label = "car"
                break
            elif w in ("dog", "cat", "animal"):
                label = w
                break

        camera = None
        if "driveway" in words:
            camera = "driveway"
        elif any(k in words for k in ("door", "doorbell", "front")):
            camera = "door"

        mask_detected = None
        if any(w in words for w in ("masked", "mask", "covering", "balaclava")) and not any(
            w in words for w in ("unmasked", "no", "without")
        ):
            mask_detected = True
        elif any(w in words for w in ("unmasked", "bare")) or (
            "no" in words and any(w in words for w in ("mask", "masks"))
        ) or ("without" in words and any(w in words for w in ("mask", "masks"))):
            mask_detected = False

        if mask_detected is not None and label is None:
            label = "person"

        start_iso, end_iso, _ = parse_timeframe_window(query, now)
        events = store.search_events(
            label=label,
            camera=camera,
            start=start_iso,
            end=end_iso,
            limit=20,
            mask_detected=mask_detected,
        )

    moment = now or datetime.now().astimezone()
    count = len(events)
    shown: list[dict[str, Any]] = []
    if count == 0:
        period = detect_timeframe(query) or "today"
        summary = _empty_summary(query, parsed.label if parsed.understood else None, period)
        latest = store.search_events(
            label=parsed.label if parsed.understood else None,
            camera=parsed.camera if parsed.understood else None,
            start=None,
            end=None,
            limit=1,
            mask_detected=parsed.mask_detected if parsed.understood else None,
        )
        if latest:
            summary += _latest_sentence(latest[0], moment, _has_cjk(query))
            shown = latest
    else:
        summary = _found_summary(query, events, moment)
        shown = events[:3]

    return {
        "query": query,
        "matched_count": count,
        "summary": summary,
        "events": events[:10],
        "media": _media_for(shown),
    }


def get_device_status(
    hub_state: HubState, lock_adapter: Any, lights: Any = None
) -> dict[str, Any]:
    """Read current security state, lock status, and light status."""
    state = hub_state.snapshot()
    lock_state = "unknown"
    lock_reachable = "unknown"
    if hasattr(lock_adapter, "get_status"):
        try:
            lock_state = lock_adapter.get_status()
            if hasattr(lock_adapter, "reachable"):
                lock_reachable = lock_adapter.reachable()
        except Exception:
            lock_state = "unknown"

    armed_text = "armed" if state.get("armed") else "disarmed"
    alarm_text = "Active alarm!" if state.get("alarm_active") else "No active alarms."
    lock_text = f"Front door is {lock_state}."

    light_text = ""
    if lights and hasattr(lights, "status"):
        l_stat = lights.status()
        if l_stat.get("enabled"):
            light_text = " Light coordinator is active."

    summary = (
        f"The security system is currently {armed_text}. {lock_text} {alarm_text}{light_text}"
    )

    return {
        "armed": state.get("armed", False),
        "alarm_active": state.get("alarm_active", False),
        "lock_status": lock_state,
        "lock_reachable": lock_reachable,
        "summary": summary,
    }


def speak_device_status(status: dict[str, Any], query: str) -> str:
    """Answer from the status reading. A small model will flip disarmed into armed."""
    armed = bool(status.get("armed"))
    lock_state = str(status.get("lock_status") or "unknown")
    if _has_cjk(query):
        text = "系统已布防。" if armed else "系统未布防。"
        if status.get("lock_reachable") == "dead":
            text += "门锁没有回应。"
        elif lock_state == "locked":
            text += "门锁着。"
        elif lock_state == "unlocked":
            text += "门未锁。"
        return text
    text = "The system is armed." if armed else "The system is disarmed."
    if status.get("lock_reachable") == "dead":
        text += " The lock is not responding."
    elif lock_state != "unknown":
        text += f" The front door is {lock_state}."
    return text


def control_light_tool(
    lights: Any, turn_on: bool, target: Optional[str] = None
) -> dict[str, Any]:
    """Turn Zigbee bulb on or off."""
    if lights is None or not hasattr(lights, "set_on"):
        return {
            "success": False,
            "summary": "Light controller is not available on this hub.",
        }

    try:
        res = lights.set_on(turn_on=turn_on)
        action = "on" if turn_on else "off"
        return {
            "success": True,
            "turn_on": turn_on,
            "summary": f"Turned the door light {action}.",
            "details": res,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "summary": f"Could not control the light: {exc}",
        }


def set_armed_tool(
    hub_state: HubState, bus: Any, actor: str, armed: bool
) -> dict[str, Any]:
    """Arm or disarm the security system."""
    changed = hub_state.set_armed(armed)
    status_str = "armed" if armed else "disarmed"
    if bus:
        payload = {
            "type": "armed_changed",
            "armed": armed,
            "actor": actor,
        }
        if hasattr(bus, "publish_threadsafe"):
            bus.publish_threadsafe(payload)
        elif hasattr(bus, "publish"):
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(bus.publish(payload))
            except RuntimeError:
                pass

    return {
        "armed": armed,
        "changed": changed,
        "summary": f"The security system is now {status_str}.",
    }
