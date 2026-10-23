"""One active meeting. Audio stays on the satellite; this stores text and minutes."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


CHUNK_PROMPT = (
    "Summarize this meeting fragment in two or three sentences. "
    "Keep decisions and tasks. Do not use markdown."
)
FINAL_PROMPT = (
    "Turn these meeting notes into minutes. Use exactly these labels, each on its own line:\n"
    "TITLE: short title\n"
    "SUMMARY: two to four sentences\n"
    "DECISIONS:\n"
    "- item\n"
    "ACTIONS:\n"
    "- item\n"
    "Use the same language as the notes. Do not use markdown or asterisks. "
    "If a section has nothing, write \"- none\"."
)
EMPTY_MINUTES = {
    "title": "Empty meeting",
    "summary": "No speech was captured.",
    "decisions": [],
    "action_items": [],
}


_MINUTE_LABEL = re.compile(
    r"(TITLE|SUMMARY|DECISIONS|ACTIONS|ACTION ITEMS)\s*:",
    re.IGNORECASE,
)


def parse_minutes(text: str) -> dict[str, Any]:
    """Read the labeled minutes the model is asked to return."""
    cleaned = text.replace("*", "")
    parts = _MINUTE_LABEL.split(cleaned)
    sections: dict[str, str] = {}
    if len(parts) >= 3:
        pairs = parts[1:]
        for label, body in zip(pairs[0::2], pairs[1::2]):
            sections[label.upper()] = body.strip()
    title = sections.get("TITLE", "").splitlines()[0].strip() if sections.get("TITLE") else ""
    summary = " ".join(sections.get("SUMMARY", "").split())
    decisions = _minute_items(sections.get("DECISIONS", ""))
    actions = _minute_items(sections.get("ACTIONS") or sections.get("ACTION ITEMS") or "")
    if not summary and text.strip() and not sections:
        summary = " ".join(cleaned.split())
    return {
        "title": title or "Meeting",
        "summary": summary,
        "decisions": decisions,
        "action_items": actions,
    }


def _minute_items(body: str) -> list[str]:
    if not body:
        return []
    pieces = body.replace(" - ", "\n").splitlines()
    items = []
    for piece in pieces:
        item = piece.strip().lstrip("-").strip()
        if item and item.lower() != "none":
            items.append(item)
    return items


def reduce_chunk(text: str, chat: Callable[..., str]) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    try:
        note = chat(
            [
                {"role": "system", "content": CHUNK_PROMPT},
                {"role": "user", "content": cleaned[:1500]},
            ],
            max_new_tokens=120,
            timeout=30.0,
        )
    except Exception:
        note = ""
    return note.strip() or cleaned[:400]


def write_minutes(notes: list[str], chat: Callable[..., str]) -> dict[str, Any]:
    if not any(note.strip() for note in notes):
        return dict(EMPTY_MINUTES)
    body = "\n".join(f"- {note.strip()}" for note in notes if note.strip())
    try:
        raw = chat(
            [
                {"role": "system", "content": FINAL_PROMPT},
                {"role": "user", "content": body[:1800]},
            ],
            max_new_tokens=320,
            timeout=45.0,
        )
    except Exception:
        raw = ""
    if not raw.strip():
        return {
            "title": "Meeting",
            "summary": " ".join(notes)[:800],
            "decisions": [],
            "action_items": [],
        }
    return parse_minutes(raw)


class MeetingLog:
    def __init__(self, directory: Path, bus: Any = None) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active: Optional[dict[str, Any]] = None
        self._bus = bus

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                return {"already": True, "state": self._active["state"], "id": self._active["id"]}
            meeting_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
            self._active = {
                "id": meeting_id,
                "state": "recording",
                "started_at": _now(),
                "chunks": [],
                "notes": [],
            }
            result = {"already": False, "state": "recording", "id": meeting_id}
        self._notify({"type": "meeting_changed", "state": "recording", "id": meeting_id})
        return result

    def active(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._active is None:
                return None
            return {
                "id": self._active["id"],
                "state": self._active["state"],
                "started_at": self._active["started_at"],
                "chunks": len(self._active["chunks"]),
            }

    def add_chunk(self, text: str, chat: Callable[..., str]) -> dict[str, Any]:
        cleaned = " ".join(text.split())
        if not cleaned:
            return {"ok": False, "message": "empty"}
        with self._lock:
            if self._active is None:
                return {"ok": False, "message": "no meeting"}
            meeting = self._active
        note = reduce_chunk(cleaned, chat)
        with self._lock:
            if self._active is None or self._active["id"] != meeting["id"]:
                return {"ok": False, "message": "no meeting"}
            self._active["chunks"].append(cleaned)
            if note:
                self._active["notes"].append(note)
            return {"ok": True, "id": meeting["id"], "chunks": len(self._active["chunks"])}

    def request_stop(self) -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                return {"had_meeting": False, "state": "idle"}
            self._active["state"] = "stopping"
            return {"had_meeting": True, "state": "stopping", "id": self._active["id"]}

    def finish(self, chat: Callable[..., str]) -> dict[str, Any]:
        with self._lock:
            meeting = self._active
            self._active = None
        if meeting is None:
            latest = self.latest()
            if latest:
                return {"had_meeting": True, "state": "ended", **_public(latest)}
            return {"had_meeting": False, "state": "idle", **EMPTY_MINUTES}
        minutes = write_minutes(list(meeting["notes"]), chat)
        saved = {
            "id": meeting["id"],
            "started_at": meeting["started_at"],
            "ended_at": _now(),
            "chunks": meeting["chunks"],
            "notes": meeting["notes"],
            **minutes,
        }
        path = self._dir / f"{meeting['id']}.json"
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        public = _public(saved)
        self._notify({"type": "meeting_changed", "state": "ended", "id": public["id"]})
        return {"had_meeting": True, "state": "ended", **public}

    def _notify(self, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_threadsafe(payload)
        except Exception:
            return

    def latest(self) -> Optional[dict[str, Any]]:
        meetings = self.list_meetings()
        return meetings[0] if meetings else None

    def list_meetings(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("id"):
                found.append(_public(data))
        found.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return found[:20]


def _public(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "title": data.get("title") or "Meeting",
        "summary": data.get("summary") or "",
        "decisions": list(data.get("decisions") or []),
        "action_items": list(data.get("action_items") or []),
    }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
