"""Notes live as JSON. Pictures are files beside them."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

TITLE_PROMPT = (
    "Give this note a short title. Reply with the title only. "
    "Use the same language as the note. Do not use markdown."
)


def strip_note_command(text: str) -> str:
    cleaned = " ".join(text.split())
    for phrase in ("记下来", "记个笔记"):
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"(?i)\b(make|take) a note(?: of| that)?\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bnote that\b", " ", cleaned)
    return " ".join(cleaned.split())


def search_notes(notes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().casefold()
    if not needle:
        return notes
    found = []
    for note in notes:
        haystack = f"{note.get('title', '')}\n{note.get('body', '')}".casefold()
        if needle in haystack:
            found.append(note)
    return found


class Library:
    def __init__(self, directory: Path, bus: Any = None) -> None:
        self._dir = directory
        self._notes = directory / "notes"
        self._pictures = directory / "pictures"
        self._notes.mkdir(parents=True, exist_ok=True)
        self._pictures.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._bus = bus
        self._active: Optional[dict[str, Any]] = None

    def start_dictation(self) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                return {"already": True, "state": "recording", "id": self._active["id"]}
            note_id = _new_id()
            self._active = {"id": note_id, "state": "recording", "chunks": []}
            return {"already": False, "state": "recording", "id": note_id}

    def active(self) -> Optional[dict[str, Any]]:
        with self._lock:
            if self._active is None:
                return None
            return {
                "id": self._active["id"],
                "state": self._active["state"],
                "chunks": len(self._active["chunks"]),
            }

    def add_chunk(self, text: str) -> dict[str, Any]:
        cleaned = " ".join(text.split())
        if not cleaned:
            return {"ok": False, "message": "empty"}
        with self._lock:
            if self._active is None:
                return {"ok": False, "message": "no note"}
            self._active["chunks"].append(cleaned)
            return {"ok": True, "id": self._active["id"], "chunks": len(self._active["chunks"])}

    def finish_dictation(self, chat: Callable[..., str]) -> dict[str, Any]:
        with self._lock:
            active = self._active
            self._active = None
        if active is None:
            return {"had_note": False, "state": "idle"}
        body = "\n".join(active["chunks"]).strip()
        if not body:
            return {"had_note": False, "state": "empty"}
        return {"had_note": True, "state": "saved", **self._save(body, "", chat, note_id=active["id"])}

    def add_text(self, body: str, title: str, chat: Optional[Callable[..., str]] = None) -> dict[str, Any]:
        cleaned = strip_note_command(body) or " ".join(body.split())
        if not cleaned:
            return {"ok": False, "message": "empty"}
        saved = self._save(cleaned, title.strip(), chat)
        return {"ok": True, **saved}

    def add_picture(self, note_id: str, filename: str, data: bytes) -> Optional[dict[str, Any]]:
        note = self.get(note_id)
        if note is None or not data:
            return None
        suffix = Path(filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".jpg"
        folder = self._pictures / note_id
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{len(list(folder.glob('*'))) + 1}{suffix}"
        (folder / name).write_bytes(data)
        pictures = list(note.get("pictures") or [])
        pictures.append(name)
        note["pictures"] = pictures
        self._write(note)
        self._notify({"type": "library_changed", "id": note_id})
        return note

    def picture_path(self, note_id: str, name: str) -> Optional[Path]:
        safe = Path(name).name
        path = self._pictures / note_id / safe
        if path.is_file():
            return path
        return None

    def get(self, note_id: str) -> Optional[dict[str, Any]]:
        path = self._notes / f"{note_id}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def list_notes(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in self._notes.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("id"):
                found.append(data)
        found.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return found

    def search(self, query: str) -> list[dict[str, Any]]:
        return search_notes(self.list_notes(), query)

    def _save(
        self,
        body: str,
        title: str,
        chat: Optional[Callable[..., str]],
        note_id: str = "",
    ) -> dict[str, Any]:
        chosen = title.strip() or _title_from_model(body, chat) or _first_line(body)
        note = {
            "id": note_id or _new_id(),
            "title": chosen,
            "body": body,
            "created_at": _now(),
            "pictures": [],
        }
        self._write(note)
        self._notify({"type": "library_changed", "id": note["id"]})
        return note

    def _write(self, note: dict[str, Any]) -> None:
        path = self._notes / f"{note['id']}.json"
        path.write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")

    def _notify(self, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_threadsafe(payload)
        except Exception:
            return


def _title_from_model(body: str, chat: Optional[Callable[..., str]]) -> str:
    if chat is None:
        return ""
    try:
        raw = chat(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": body[:1200]},
            ],
            max_new_tokens=40,
            timeout=25.0,
        )
    except Exception:
        return ""
    title = " ".join((raw or "").replace("*", "").split())
    return title[:80]


def _first_line(body: str) -> str:
    line = body.strip().splitlines()[0].strip()
    return line[:80] or "Note"


def _new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
