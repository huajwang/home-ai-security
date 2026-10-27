"""TURN credentials for Cloud Link calls only.

LAN and Tailscale keep an empty ICE list, so those calls stay on the direct path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from hub import config


def uses_cloud_link(host: str) -> bool:
    name = host.split(":")[0].strip().lower().rstrip(".")
    suffix = config.LINK_SUFFIX.strip().lower()
    if not name or not suffix:
        return False
    if not suffix.startswith("."):
        suffix = "." + suffix
    return name.endswith(suffix)


def ice_servers_for_host(host: str, now: float | None = None) -> list[dict[str, str]]:
    if not uses_cloud_link(host):
        return []
    if not config.TURN_HOST or not config.TURN_SECRET:
        return []
    expiry = int((now if now is not None else time.time()) + 3600)
    username = f"{expiry}:home"
    digest = hmac.new(config.TURN_SECRET.encode(), username.encode(), hashlib.sha1).digest()
    return [
        {
            "urls": f"turn:{config.TURN_HOST}:{config.TURN_PORT}",
            "username": username,
            "credential": base64.b64encode(digest).decode(),
        }
    ]
