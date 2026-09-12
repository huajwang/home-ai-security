"""Password hashing, JWT access tokens, and first-owner bootstrap."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from hub import config
from hub.storage import Store, utcnow


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(digest, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret(store: Store) -> str:
    if config.JWT_SECRET:
        return config.JWT_SECRET
    existing = store.get_kv("jwt_secret")
    if existing:
        return existing
    secret = secrets.token_urlsafe(48)
    store.set_kv("jwt_secret", secret)
    return secret


def issue_access_token(store: Store, user: dict[str, Any], device: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "can_unlock": bool(user["can_unlock"]),
        "device_id": device["id"],
        "device_role": device["device_role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, _secret(store), algorithm="HS256")


def decode_access_token(store: Store, token: str) -> dict[str, Any]:
    return jwt.decode(token, _secret(store), algorithms=["HS256"])


def issue_refresh_token(store: Store, user_id: int, device_id: int) -> str:
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TOKEN_DAYS)
    store.save_refresh(user_id, device_id, hash_token(token), expires.replace(microsecond=0).isoformat())
    return token


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "can_unlock": bool(user["can_unlock"]),
    }


def bootstrap_owner(store: Store) -> None:
    if store.user_count() > 0:
        return
    store.create_user(
        username=config.OWNER_USERNAME,
        password_hash=hash_password(config.OWNER_PASSWORD),
        role="owner",
        can_unlock=True,
    )
    print(f"Bootstrapped owner account '{config.OWNER_USERNAME}'. Change HUB_OWNER_PASSWORD after first login.")


def refresh_is_valid(row: dict[str, Any] | None) -> bool:
    if row is None or int(row["revoked"]) == 1:
        return False
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow()
