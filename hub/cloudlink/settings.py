"""Cloud Link settings. All of them stay empty unless this house opts in."""

from __future__ import annotations

from hub import config


def link_enabled() -> bool:
    return bool(config.LINK_URL and config.LINK_HOSTNAME and config.LINK_FERNET_KEY)


def link_status() -> dict[str, str | bool | None]:
    if not link_enabled():
        return {"enabled": False, "url": None, "hostname": None}
    return {
        "enabled": True,
        "hostname": config.LINK_HOSTNAME,
        "url": f"https://{config.LINK_HOSTNAME}",
    }


def peer_host_port() -> tuple[str, int]:
    raw = config.LINK_URL
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    if raw.startswith("["):
        host, _, port = raw[1:].partition("]")
        port = port[1:] if port.startswith(":") else "443"
        return host, int(port or "443")
    if raw.count(":") == 1:
        host, port = raw.split(":")
        return host, int(port)
    return raw, 443


def link_certs_ready() -> bool:
    return config.LINK_CERT_FILE.is_file() and config.LINK_KEY_FILE.is_file()
