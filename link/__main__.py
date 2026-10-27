"""Run the trial relay: SNI passthrough plus the backup and voice HTTP API.

LINK_SNI_HOST and LINK_SNI_PORT choose who owns public 443. See link/SWITCH.md.
Relay mode listens on 0.0.0.0:443. Yaojia mode listens on 127.0.0.1:4430 and nginx serves the site.
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from link.app import create_app


def _keys() -> list[str]:
    raw = [item.strip() for item in os.getenv("LINK_FERNET_KEYS", "").split(",") if item.strip()]
    if not raw:
        raise SystemExit("Set LINK_FERNET_KEYS to the same value as HUB_LINK_FERNET_KEY on the hub.")
    return raw


async def _serve() -> None:
    from snitun.server.run import SniTunServerSingle

    keys = _keys()
    os.environ["LINK_FERNET_KEYS"] = ",".join(keys)
    sni_host = os.getenv("LINK_SNI_HOST", "127.0.0.1")
    sni_port = int(os.getenv("LINK_SNI_PORT", "4430"))
    http_host = os.getenv("LINK_HTTP_HOST", "127.0.0.1")
    http_port = int(os.getenv("LINK_HTTP_PORT", "8091"))
    tunnel = SniTunServerSingle(keys, host=sni_host, port=sni_port)
    await tunnel.start()
    print(f"Cloud Link SNI tunnel on {sni_host}:{sni_port}")
    config = uvicorn.Config(create_app(), host=http_host, port=http_port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await tunnel.stop()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
