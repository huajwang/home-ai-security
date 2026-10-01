"""On/off control for Zigbee bulbs on the coordinator stick."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from hub import config

ON_OFF_CLUSTER = 0x0006


class ZigbeeLights:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Any = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not config.ZIGBEE_DEVICE:
            return
        self._thread = threading.Thread(target=self._thread_main, name="zigbee-lights", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        app = self._app
        if loop is None or not loop.is_running():
            return
        if app is not None:
            future = asyncio.run_coroutine_threadsafe(app.shutdown(), loop)
            try:
                future.result(timeout=8)
            except Exception as exc:  # noqa: BLE001
                print(f"Zigbee shutdown: {exc}")
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=8)

    def status(self) -> dict[str, Any]:
        lights: list[dict[str, str]] = []
        error = self._error
        if self._app is not None and self._ready.is_set():
            try:
                lights = self.list_lights()
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
        return {
            "enabled": bool(config.ZIGBEE_DEVICE),
            "ready": self._app is not None and self._error is None,
            "error": error,
            "lights": lights,
        }

    def list_lights(self) -> list[dict[str, str]]:
        if self._app is None:
            return []
        return self._call(self._list())

    def set_on(self, turn_on: bool, ieee: str | None = None) -> dict[str, Any]:
        self._require_ready()
        return self._call(self._set_on(turn_on, ieee), timeout=60)

    def permit_join(self, seconds: int = 120) -> dict[str, Any]:
        self._require_ready()
        self._call(self._permit(seconds))
        return {
            "ok": True,
            "seconds": seconds,
            "message": "Zigbee joining is open. Power the bulb off for 5 seconds, then on.",
        }

    def _require_ready(self) -> None:
        if not config.ZIGBEE_DEVICE:
            raise RuntimeError("Zigbee dongle is not configured")
        if not self._ready.wait(40):
            raise RuntimeError("Zigbee coordinator is still starting")
        if self._error or self._app is None or self._loop is None:
            raise RuntimeError(self._error or "Zigbee coordinator is not ready")

    def _call(self, coro: Any, timeout: float = 25) -> Any:
        self._require_ready()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def _thread_main(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            from zigpy_znp.zigbee.application import ControllerApplication

            database = config.DATA_DIR / "zigbee.db"
            self._app = await ControllerApplication.new(
                {
                    "database_path": str(database),
                    "device": {
                        "path": config.ZIGBEE_DEVICE,
                        "baudrate": config.ZIGBEE_BAUD,
                    },
                },
                auto_form=True,
                start_radio=True,
            )
            print(f"Zigbee coordinator ready on {config.ZIGBEE_DEVICE}")
        except Exception as exc:  # noqa: BLE001
            self._error = f"Zigbee coordinator failed: {exc}"
            print(f"ERROR: {self._error}")
        finally:
            self._ready.set()
        if self._app is None:
            return
        stay = self._loop.create_future()
        try:
            await stay
        except asyncio.CancelledError:
            pass

    async def _permit(self, seconds: int) -> None:
        await self._app.permit(seconds)
        print(f"Zigbee permit join for {seconds}s")

    async def _list(self) -> list[dict[str, str]]:
        lights = []
        for device, _endpoint in _light_endpoints(self._app):
            lights.append({"ieee": str(device.ieee), "name": _device_name(device)})
        return lights

    async def _set_on(self, turn_on: bool, ieee: str | None) -> dict[str, Any]:
        matches = _light_endpoints(self._app)
        if ieee:
            matches = [(device, endpoint) for device, endpoint in matches if str(device.ieee) == ieee]
        if not matches:
            raise LookupError("No Zigbee bulb is paired")
        state = "on" if turn_on else "off"
        reached: list[str] = []
        missed: list[str] = []
        for device, endpoint in matches:
            try:
                cluster = endpoint.in_clusters[ON_OFF_CLUSTER]
                command = getattr(cluster, "on" if turn_on else "off", None)
                if command is None:
                    await cluster.command(0x01 if turn_on else 0x00)
                else:
                    await command()
                reached.append(str(device.ieee))
                print(f"Zigbee light {device.ieee} {state}")
            except Exception as exc:  # noqa: BLE001
                missed.append(str(device.ieee))
                print(f"Zigbee light {device.ieee} {state} failed: {exc}")
        if not reached:
            raise RuntimeError(f"No bulb acknowledged the {state} command")
        return {
            "ieee": reached[0],
            "name": "Zigbee bulb",
            "state": f"{state}, {len(reached)} of {len(matches)}",
            "reached": reached,
            "missed": missed,
        }


def _device_name(device: Any) -> str:
    model = getattr(device, "model", None) or getattr(device, "manufacturer", None)
    return str(model) if model else "Zigbee bulb"


def _light_endpoints(app: Any) -> list[tuple[Any, Any]]:
    found: list[tuple[Any, Any]] = []
    for device in app.devices.values():
        if getattr(device, "nwk", None) in {0, 0x0000}:
            continue
        endpoints = getattr(device, "endpoints", {}) or {}
        for endpoint_id, endpoint in endpoints.items():
            if endpoint_id == 0:
                continue
            clusters = getattr(endpoint, "in_clusters", {}) or {}
            if ON_OFF_CLUSTER in clusters:
                found.append((device, endpoint))
    return found
