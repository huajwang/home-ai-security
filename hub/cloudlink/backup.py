"""Encrypt a hub backup on the hub. The relay stores ciphertext only."""

from __future__ import annotations

import io
import os
import sqlite3
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hub import config

_NONCE_LEN = 12


def load_or_create_key() -> bytes:
    """Return the 32-byte key that never leaves this hub."""
    path = config.BACKUP_KEY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        raw = path.read_bytes().strip()
        key = raw if len(raw) == 32 else _b64_or_raw(raw)
        if len(key) != 32:
            raise ValueError("backup key must be 32 bytes")
        return key
    key = os.urandom(32)
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _b64_or_raw(raw: bytes) -> bytes:
    import base64

    try:
        return base64.b64decode(raw)
    except Exception:  # noqa: BLE001
        return raw


def build_archive(db_path: Path, snapshot_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        if db_path.is_file():
            snapshot = db_path.with_suffix(".backup")
            source = sqlite3.connect(db_path)
            try:
                dest = sqlite3.connect(snapshot)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
            finally:
                source.close()
            archive.add(snapshot, arcname="hub.db")
            snapshot.unlink(missing_ok=True)
        if snapshot_dir.is_dir():
            for path in sorted(snapshot_dir.iterdir()):
                if path.is_file():
                    archive.add(path, arcname=f"snapshots/{path.name}")
    return buffer.getvalue()


def encrypt_backup(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_backup(blob: bytes, key: bytes) -> bytes:
    if len(blob) < _NONCE_LEN + 16:
        raise ValueError("backup is too short")
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def upload_backup(blob: bytes, url: str, token: str, home_id: str) -> None:
    target = url.rstrip("/") + "/" + home_id
    request = urllib.request.Request(
        target,
        data=blob,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"backup upload failed: {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"backup upload failed: {exc.code}") from exc


def make_and_upload() -> bool:
    """Encrypt and upload when a backup URL is configured. Return True if sent."""
    if not config.BACKUP_URL or not config.LINK_HOSTNAME or not config.LINK_FERNET_KEY:
        return False
    key = load_or_create_key()
    archive = build_archive(config.DB_PATH, config.SNAPSHOT_DIR)
    blob = encrypt_backup(archive, key)
    upload_backup(blob, config.BACKUP_URL, config.LINK_FERNET_KEY, config.LINK_HOSTNAME)
    print(f"Cloud Link backup uploaded for {config.LINK_HOSTNAME}")
    return True
