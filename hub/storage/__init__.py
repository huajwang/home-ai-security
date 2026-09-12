"""SQLite persistence for users, devices, events, and audit."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from hub import config


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or config.DB_PATH)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                yield cur
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self.cursor() as cur:
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    can_unlock INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    device_name TEXT NOT NULL,
                    device_role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    device_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    snapshot_path TEXT
                );

                CREATE TABLE IF NOT EXISTS lock_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    device_id INTEGER,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def get_kv(self, key: str) -> str | None:
        with self.cursor() as cur:
            row = cur.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_kv(self, key: str, value: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def user_count(self) -> int:
        with self.cursor() as cur:
            row = cur.execute("SELECT COUNT(*) AS n FROM users").fetchone()
            return int(row["n"])

    def create_user(self, username: str, password_hash: str, role: str, can_unlock: bool) -> dict[str, Any]:
        now = utcnow()
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO users(username, password_hash, role, can_unlock, created_at) VALUES(?,?,?,?,?)",
                (username, password_hash, role, 1 if can_unlock else 0, now),
            )
            user_id = cur.lastrowid
        return self.get_user(user_id)  # type: ignore[return-value]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.cursor() as cur:
            row = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_name(self, username: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            row = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    def create_device(self, user_id: int, device_name: str, device_role: str) -> dict[str, Any]:
        now = utcnow()
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO devices(user_id, device_name, device_role, created_at) VALUES(?,?,?,?)",
                (user_id, device_name, device_role, now),
            )
            device_id = cur.lastrowid
        return self.get_device(device_id)  # type: ignore[return-value]

    def get_device(self, device_id: int) -> dict[str, Any] | None:
        with self.cursor() as cur:
            row = cur.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            return dict(row) if row else None

    def list_devices(self) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            rows = cur.execute(
                """
                SELECT d.*, u.username
                FROM devices d
                JOIN users u ON u.id = d.user_id
                ORDER BY d.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_device(self, device_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute("UPDATE refresh_tokens SET revoked = 1 WHERE device_id = ?", (device_id,))
            cur.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            return cur.rowcount > 0

    def save_refresh(self, user_id: int, device_id: int, token_hash: str, expires_at: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO refresh_tokens(user_id, device_id, token_hash, expires_at, revoked) VALUES(?,?,?,?,0)",
                (user_id, device_id, token_hash, expires_at),
            )

    def get_refresh(self, token_hash: str) -> dict[str, Any] | None:
        with self.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            return dict(row) if row else None

    def revoke_refresh(self, token_hash: str) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?", (token_hash,))

    def revoke_device_refresh(self, device_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE refresh_tokens SET revoked = 1 WHERE device_id = ?", (device_id,))

    def add_event(self, label: str, confidence: float, snapshot_path: str | None) -> dict[str, Any]:
        now = utcnow()
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO events(ts, label, confidence, snapshot_path) VALUES(?,?,?,?)",
                (now, label, confidence, snapshot_path),
            )
            event_id = cur.lastrowid
        return self.get_event(event_id)  # type: ignore[return-value]

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        with self.cursor() as cur:
            row = cur.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return dict(row) if row else None

    def list_events(self, since: str | None, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self.cursor() as cur:
            if since:
                rows = cur.execute(
                    "SELECT * FROM events WHERE ts > ? ORDER BY id DESC LIMIT ?",
                    (since, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    def add_lock_audit(
        self,
        actor: str,
        device_id: int | None,
        action: str,
        result: str,
        reason: str | None,
    ) -> dict[str, Any]:
        now = utcnow()
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO lock_audit(ts, actor, device_id, action, result, reason) VALUES(?,?,?,?,?,?)",
                (now, actor, device_id, action, result, reason),
            )
            audit_id = cur.lastrowid
        with self.cursor() as cur:
            row = cur.execute("SELECT * FROM lock_audit WHERE id = ?", (audit_id,)).fetchone()
            return dict(row) if row else {"id": audit_id, "ts": now}

    def list_lock_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM lock_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
