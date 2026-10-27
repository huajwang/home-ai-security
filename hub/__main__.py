"""Run: python -m hub"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from hub import config
from hub.tls import advertised_hub_urls, ensure_tls_files


async def _run_servers(cert, key) -> None:
    https_cfg = uvicorn.Config(
        "hub.app:app",
        host=config.HOST,
        port=config.PORT,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
        reload=False,
    )
    https_server = uvicorn.Server(https_cfg)
    tasks = [https_server.serve()]

    if config.HTTP_PORT > 0:
        http_cfg = uvicorn.Config(
            "hub.app:app",
            host=config.HOST,
            port=config.HTTP_PORT,
            reload=False,
        )
        http_server = uvicorn.Server(http_cfg)
        tasks.append(http_server.serve())

    from hub.cloudlink.settings import link_certs_ready

    if link_certs_ready():
        link_cfg = uvicorn.Config(
            "hub.app:app",
            host="127.0.0.1",
            port=config.LINK_LOCAL_PORT,
            ssl_certfile=str(config.LINK_CERT_FILE),
            ssl_keyfile=str(config.LINK_KEY_FILE),
            reload=False,
        )
        tasks.append(uvicorn.Server(link_cfg).serve())
        print(f"Cloud Link local TLS on 127.0.0.1:{config.LINK_LOCAL_PORT}")

    await asyncio.gather(*tasks)


def main() -> None:
    config.ensure_dirs()
    cert, key = ensure_tls_files()
    os.chdir(config.ROOT)
    print("Hub URLs for Android & iOS:")
    for url in advertised_hub_urls():
        print(f"  {url}")
    print("Sign in as owner / changeme, then tap Talk for the camera stream.")

    if config.HTTP_PORT > 0:
        try:
            asyncio.run(_run_servers(cert, key))
        except KeyboardInterrupt:
            pass
    else:
        uvicorn.run(
            "hub.app:app",
            host=config.HOST,
            port=config.PORT,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            reload=False,
        )


if __name__ == "__main__":
    main()
