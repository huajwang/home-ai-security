"""Dial the Cloud Link relay. This process does not start the hub."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

_RETRY_SECONDS = 15


@dataclass(frozen=True)
class Settings:
    url: str
    hostname: str
    fernet_key: str
    local_port: int
    cert_file: Path
    key_file: Path

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.hostname and self.fernet_key)

    def certs_ready(self) -> bool:
        return self.cert_file.is_file() and self.key_file.is_file()


def peer_host_port(raw: str) -> tuple[str, int]:
    value = raw.strip()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    if value.startswith("["):
        host, _, port = value[1:].partition("]")
        port = port[1:] if port.startswith(":") else "443"
        return host, int(port or "443")
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, int(port)
    return value, 443


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    cert_dir = Path(os.getenv("HUB_CERT_DIR", str(root / "certs")))
    return Settings(
        url=os.getenv("HUB_LINK_URL", "").strip(),
        hostname=os.getenv("HUB_LINK_HOSTNAME", "").strip(),
        fernet_key=os.getenv("HUB_LINK_FERNET_KEY", "").strip(),
        local_port=int(os.getenv("HUB_LINK_LOCAL_PORT", "8444")),
        cert_file=Path(os.getenv("HUB_LINK_CERT", str(cert_dir / "link.pem"))),
        key_file=Path(os.getenv("HUB_LINK_KEY", str(cert_dir / "link-key.pem"))),
    )


async def run(settings: Settings) -> None:
    if not settings.enabled:
        print("Cloud Link is off. Set HUB_LINK_URL, HUB_LINK_HOSTNAME, and HUB_LINK_FERNET_KEY.")
        return
    if not settings.certs_ready():
        print("Cloud Link is configured but link.pem is missing. The relay stays disconnected.")
        return
    while True:
        try:
            await _session(settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"Cloud Link will retry: {exc}")
        await asyncio.sleep(_RETRY_SECONDS)


async def _session(settings: Settings) -> None:
    from snitun.client.client_peer import ClientPeer
    from snitun.client.connector import Connector
    from snitun.utils.aes import generate_aes_keyset
    from snitun.utils.server import generate_client_token

    host, port = peer_host_port(settings.url)
    aes_key, aes_iv = generate_aes_keyset()
    token = generate_client_token(
        [settings.fernet_key],
        timedelta(days=2),
        settings.hostname,
        aes_key,
        aes_iv,
    )
    connector = Connector("127.0.0.1", settings.local_port)
    client = ClientPeer(host, port)
    print(f"Cloud Link dialing {host}:{port} as {settings.hostname}")
    await client.start(connector, token, aes_key, aes_iv)
    while client.is_connected:
        await asyncio.sleep(5)


def main() -> None:
    asyncio.run(run(load_settings()))


if __name__ == "__main__":
    main()
