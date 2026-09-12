"""Run: python -m hub"""

from __future__ import annotations

import os

import uvicorn

from hub import config
from hub.tls import advertised_hub_urls, ensure_tls_files


def main() -> None:
    config.ensure_dirs()
    cert, key = ensure_tls_files()
    os.chdir(config.ROOT)
    print("Hub URLs for the Android phone:")
    for url in advertised_hub_urls():
        print(f"  {url}")
    print("Sign in as owner / changeme, then tap Talk for the camera stream.")
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
