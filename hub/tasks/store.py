"""One JSON file per spoken task."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

TASK_PROMPT = (
    "Extract one home task. Reply with exactly these two lines:\n"
    "TEXT: the task without the command words\n"
    "DUE: a date or time if one was spoken, otherwise none\n"
    "Do not use markdown."
)

_DUE = re.compile(
    r"(今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天]|下周|"
    r"today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    re.IGNORECASE,
)


def strip_command(text: str) -> str:
    cleaned = " ".join(text.split())
    for phrase in ("提醒我", "购物清单", "保养记录"):
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"(?i)\bremind me(?: to)?\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\badd to the shopping list\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bto the shopping list\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bshopping list\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(log maintenance|maintenance log)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)^(?:please\s+)?(?:add|put)\s+", "", cleaned.strip())
    return " ".join(cleaned.split())


def due_phrase(text: str) -> str:
    match = _DUE.search(text)
    return match.group(0) if match else ""


def parse_task_reply(raw: str) -> tuple[str, str]:
    text = ""
    due = ""
    for line in raw.replace("*", "").splitlines():
        label, _, rest = line.strip().partition(":")
        key = label.strip().upper()
        if key == "TEXT":
            text = rest.strip()
        elif key == "DUE":
            due = rest.strip()
    if due.lower() in {"none", "n/a", "无", "没有"}:
        due = ""
    return text, due


def normalize_task(utterance: str, chat: Callable[..., str]) -> tuple[str, str]:
    fallback = strip_command(utterance) or " ".join(utterance.split())
    due = due_phrase(fallback)
    try:
        raw = chat(
            [
                {"role": "system", "content": TASK_PROMPT},
                {"role": "user", "content": utterance[:800]},
            ],
            max_new_tokens=80,
            timeout=25.0,
        )
    except Exception:
        raw = ""
    text, model_due = parse_task_reply(raw or "")
    return (text or fallback), (model_due or due)


class TaskLog:
    def __init__(self, directory: Path, bus: Any = None) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._bus = bus

    def add(self, kind: str, utterance: str, chat: Callable[..., str]) -> dict[str, Any]:
        text, due = normalize_task(utterance, chat)
        item = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4],
            "kind": kind,
            "text": text,
            "due": due,
            "created_at": _now(),
            "done": False,
        }
        self._write(item)
        self._notify({"type": "task_changed", "id": item["id"], "done": False})
        return item

    def list_open(self) -> list[dict[str, Any]]:
        return [item for item in self.list_all() if not item.get("done")]

    def list_all(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("id"):
                found.append(data)
        found.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return found

    def mark_done(self, task_id: str) -> Optional[dict[str, Any]]:
        path = self._dir / f"{task_id}.json"
        if not path.is_file():
            return None
        with self._lock:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["done"] = True
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._notify({"type": "task_changed", "id": task_id, "done": True})
        return data

    def _write(self, item: dict[str, Any]) -> None:
        path = self._dir / f"{item['id']}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

    def _notify(self, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_threadsafe(payload)
        except Exception:
            return


def speak_open_tasks(items: list[dict[str, Any]], chinese: bool) -> str:
    if not items:
        return "清单是空的。" if chinese else "The list is empty."
    parts = []
    for item in items[:6]:
        due = f"（{item['due']}）" if item.get("due") and chinese else ""
        if item.get("due") and not chinese:
            due = f", {item['due']}"
        parts.append(f"{item.get('text', '')}{due}")
    if chinese:
        return "清单上有：" + "；".join(parts) + "。"
    return "On the list: " + "; ".join(parts) + "."


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
