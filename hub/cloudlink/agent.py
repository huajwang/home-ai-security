"""Dial the relay and reconnect. Does nothing unless Cloud Link is configured."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from hub import config
from hub.cloudlink.backup import make_and_upload
from hub.cloudlink.settings import link_certs_ready, link_enabled, peer_host_port

_RETRY_SECONDS = 15
_BACKUP_EVERY = 24 * 60 * 60


class LinkAgent:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return link_enabled()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self.enabled or self._task is not None:
            return
        self._task = loop.create_task(self.run())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        if not link_certs_ready():
            print("Cloud Link is configured but link.pem is missing. The relay stays disconnected.")
            return
        next_backup = 0.0
        while True:
            try:
                next_backup = await self._session(next_backup)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"Cloud Link will retry: {exc}")
            await asyncio.sleep(_RETRY_SECONDS)

    async def _session(self, next_backup: float) -> float:
        from snitun.client.client_peer import ClientPeer
        from snitun.client.connector import Connector
        from snitun.utils.aes import generate_aes_keyset
        from snitun.utils.server import generate_client_token

        host, port = peer_host_port()
        aes_key, aes_iv = generate_aes_keyset()
        token = generate_client_token(
            [config.LINK_FERNET_KEY],
            timedelta(days=2),
            config.LINK_HOSTNAME,
            aes_key,
            aes_iv,
        )
        connector = Connector("127.0.0.1", config.LINK_LOCAL_PORT)
        client = ClientPeer(host, port)
        print(f"Cloud Link dialing {host}:{port} as {config.LINK_HOSTNAME}")
        await client.start(connector, token, aes_key, aes_iv)
        loop = asyncio.get_running_loop()
        while client.is_connected:
            now = loop.time()
            if config.BACKUP_URL and now >= next_backup:
                try:
                    await asyncio.to_thread(make_and_upload)
                except Exception as exc:  # noqa: BLE001
                    print(f"Cloud Link backup will retry: {exc}")
                next_backup = now + _BACKUP_EVERY
            await asyncio.sleep(5)
        return next_backup
