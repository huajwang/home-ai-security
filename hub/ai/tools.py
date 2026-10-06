"""Tools and functions for the Home AI Voice Assistant.

Includes:
- Security Briefings over specified timeframes
- Natural event search
- Device status and lock inspection (unlock strictly forbidden!)
- Zigbee light control
- Arm/disarm control
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from hub.search.query import EventQuery, parse_question
from hub.state import HubState
from hub.storage import Store


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_timeframe_window(
    timeframe: str, now: Optional[datetime] = None
) -> tuple[Optional[str], Optional[str], str]:
    """Parse timeframe string like 'today', 'yesterday', 'last_night' into ISO start, end, and label."""
    moment = now or datetime.now().astimezone()
    tf = timeframe.lower().strip().replace(" ", "_")

    if tf in ("yesterday", "last_day"):
        day = moment - timedelta(days=1)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return _to_utc_iso(start), _to_utc_iso(end), "yesterday"
    elif tf in ("last_night", "night"):
        # If morning now, last night means previous evening/night
        day = moment - timedelta(days=1) if moment.hour < 12 else moment
        start = day.replace(hour=21, minute=0, second=0, microsecond=0)
        end = day.replace(hour=23, minute=59, second=59, microsecond=0)
        return _to_utc_iso(start), _to_utc_iso(end), "last night"
    elif tf in ("this_morning", "morning"):
        start = moment.replace(hour=5, minute=0, second=0, microsecond=0)
        end = moment.replace(hour=12, minute=0, second=0, microsecond=0)
        return _to_utc_iso(start), _to_utc_iso(end), "this morning"
    elif tf in ("this_afternoon", "afternoon"):
        start = moment.replace(hour=12, minute=0, second=0, microsecond=0)
        end = moment.replace(hour=17, minute=0, second=0, microsecond=0)
        return _to_utc_iso(start), _to_utc_iso(end), "this afternoon"
    elif tf in ("this_week", "past_week"):
        start = (moment - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = moment
        return _to_utc_iso(start), _to_utc_iso(end), "the past 7 days"
    else:  # default 'today'
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return _to_utc_iso(start), _to_utc_iso(end), "today"


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

        summary = (
            f"Security briefing for {label_name}: {total_count} total event"
            f"{'s' if total_count != 1 else ''} recorded, including {breakdown}.{latest_str}"
        )

    return {
        "timeframe": label_name,
        "total_events": total_count,
        "counts_by_label": counts_by_label,
        "counts_by_camera": counts_by_camera,
        "summary": summary,
        "events": events[:10],
    }


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
        )
    else:
        # Fallback keyword extraction if strict parse_question wasn't fully understood
        words = [w.strip(".,?!").lower() for w in query.split()]
        label = None
        for w in words:
            if w in ("person", "someone", "people", "visitor"):
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

        start_iso, end_iso, _ = parse_timeframe_window(query, now)
        events = store.search_events(
            label=label,
            camera=camera,
            start=start_iso,
            end=end_iso,
            limit=20,
        )

    count = len(events)
    if count == 0:
        summary = f"I found no events matching '{query}'."
    else:
        details = []
        for ev in events[:3]:
            lbl = ev.get("label", "event")
            cam = ev.get("camera", "camera")
            ts = ev.get("ts", "")
            try:
                dt = datetime.fromisoformat(ts)
                t_str = dt.strftime("%I:%M %p")
            except Exception:
                t_str = ts
            details.append(f"{lbl} at {cam} around {t_str}")
        summary = f"Found {count} event{'s' if count != 1 else ''}: " + "; ".join(details) + "."

    return {
        "query": query,
        "matched_count": count,
        "summary": summary,
        "events": events[:10],
    }


def get_device_status(
    hub_state: HubState, lock_adapter: Any, lights: Any = None
) -> dict[str, Any]:
    """Read current security state, lock status, and light status."""
    state = hub_state.snapshot()
    lock_state = "unknown"
    if hasattr(lock_adapter, "get_status"):
        try:
            lock_state = lock_adapter.get_status()
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
        "summary": summary,
    }


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
    if changed and bus and hasattr(bus, "publish"):
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                bus.publish(
                    {
                        "type": "armed_changed",
                        "armed": armed,
                        "actor": actor,
                    }
                )
            )
        except RuntimeError:
            pass

    return {
        "armed": armed,
        "changed": changed,
        "summary": f"The security system is now {status_str}.",
    }
