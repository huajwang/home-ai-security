"""On/off control for Zigbee bulbs on the coordinator stick."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from hub import config
from hub.devices.door_sensor import DoorRadio, looks_like_contact
from hub.devices.scene_remote import ButtonPress, SceneRadio, looks_like_scene_remote

ON_OFF_CLUSTER = 0x0006
RETRY_SECONDS = 5


class ZigbeeLights:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: Any = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._stop = threading.Event()
        self._stay: asyncio.Future[None] | None = None
        self._button_handler: Any = None
        self._contact_handler: Any = None
        self._last_button: str | None = None
        self._on = False
        self._on_lock = threading.Lock()
        self._scene = SceneRadio(self)
        self._doors = DoorRadio(self)

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
        stay = self._stay
        if stay is not None and not stay.done():
            loop.call_soon_threadsafe(stay.cancel)
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
        remotes: list[dict[str, str]] = []
        error = self._error
        if self._app is not None and self._ready.is_set():
            try:
                lights = self.list_lights()
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            try:
                remotes = self.list_remotes()
            except Exception as exc:  # noqa: BLE001
                error = error or str(exc)
        return {
            "enabled": bool(config.ZIGBEE_DEVICE),
            "ready": self._app is not None and self._error is None,
            "error": error,
            "lights": lights,
            "remotes": remotes,
            "last_button": self._last_button,
        }

    def list_lights(self) -> list[dict[str, str]]:
        if self._app is None:
            return []
        return self._call(self._list())

    def list_remotes(self) -> list[dict[str, str]]:
        if self._app is None or not self._ready.is_set() or self._loop is None:
            return []
        return self._call(self._list_remotes())

    def set_on(self, turn_on: bool, ieee: str | None = None) -> dict[str, Any]:
        self._require_ready()
        return self._call(self._set_on(turn_on, ieee), timeout=60)

    def is_on(self) -> bool:
        with self._on_lock:
            return self._on

    def toggle(self, ieee: str | None = None) -> dict[str, Any]:
        self._require_ready()
        try:
            current = self._call(self._current_on(ieee), timeout=12)
        except Exception as exc:  # noqa: BLE001
            print(f"Zigbee light state unread: {exc}")
            current = None
        turn_on = (not self.is_on()) if current is None else (not current)
        return self.set_on(turn_on, ieee)

    def set_button_handler(self, handler: Any) -> None:
        self._button_handler = handler

    def set_contact_handler(self, handler: Any) -> None:
        self._contact_handler = handler

    def note_contact(self, ieee: str, opened: bool, model: str = "", confirmed: bool = False) -> None:
        """Run a contact report off the radio thread."""
        handler = self._contact_handler
        if handler is None:
            print(f"Door sensor {ieee}: {'door opened' if opened else 'door closed'}")
            return
        threading.Thread(
            target=self._run_contact,
            args=(handler, ieee, opened, model, confirmed),
            name="door-sensor",
            daemon=True,
        ).start()

    def _run_contact(self, handler: Any, ieee: str, opened: bool, model: str, confirmed: bool = False) -> None:
        try:
            try:
                handler(ieee, opened, model, confirmed=confirmed)
            except TypeError:
                handler(ieee, opened, model)
        except Exception as exc:  # noqa: BLE001
            print(f"Door sensor {ieee} failed: {exc}")

    def list_contacts(self) -> list[dict[str, str]]:
        if self._app is None or not self._ready.is_set() or self._loop is None:
            return []
        return self._call(self._list_contacts())

    def note_button(self, press: ButtonPress) -> None:
        """Run a remote press off the radio thread so a light command cannot deadlock it."""
        self._last_button = f"{press.button} {press.kind}"
        handler = self._button_handler
        if handler is None:
            print(f"Scene remote button {press.button} {press.kind}")
            return
        threading.Thread(
            target=self._run_button,
            args=(handler, press),
            name="scene-remote",
            daemon=True,
        ).start()

    def _run_button(self, handler: Any, press: ButtonPress) -> None:
        try:
            handler(press)
        except Exception as exc:  # noqa: BLE001
            print(f"Scene remote button {press.button} {press.kind} failed: {exc}")

    def _remember(self, turn_on: bool) -> None:
        with self._on_lock:
            self._on = turn_on

    def permit_join(self, seconds: int = 120) -> dict[str, Any]:
        self._require_ready()
        self._call(self._permit(seconds))
        return {
            "ok": True,
            "seconds": seconds,
            "message": (
                "Zigbee joining is open. Power a bulb off for 5 seconds, then on. "
                "For the scene remote, hold button 1 for 10 seconds until the LEDs flash quickly."
            ),
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
        while not self._stop.is_set():
            try:
                await self._open_radio()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._app = None
                self._error = f"Zigbee coordinator failed: {exc}"
                print(f"ERROR: {self._error}")
                self._ready.set()
                try:
                    await asyncio.wait_for(self._stopped(), timeout=RETRY_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue
            self._error = None
            self._ready.set()
            print(f"Zigbee coordinator ready on {config.ZIGBEE_DEVICE}")
            try:
                await self._stopped()
            except asyncio.CancelledError:
                if self._stop.is_set():
                    break
            if self._stop.is_set():
                break
            await self._close_radio()
            print("Zigbee coordinator stopped. Opening it again.")

    def _on_radio_lost(self, exc: BaseException) -> None:
        """The stick was unplugged. Drop the dead radio so the open loop starts again."""
        if self._stop.is_set() or not self._ready.is_set():
            return
        self._ready.clear()
        self._error = f"Zigbee dongle disconnected: {exc}"
        print(self._error)
        stay = self._stay
        if stay is not None and not stay.done():
            stay.cancel()

    async def _close_radio(self) -> None:
        app = self._app
        self._app = None
        if app is None:
            return
        try:
            await asyncio.wait_for(app.shutdown(), timeout=8)
        except Exception as exc:  # noqa: BLE001
            print(f"Zigbee shutdown: {exc}")

    async def _open_radio(self) -> None:
        from zigpy_znp.zigbee.application import ControllerApplication

        database = config.DATA_DIR / "zigbee.db"
        app = await ControllerApplication.new(
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
        self._app = app
        if hasattr(app, "add_listener"):
            app.add_listener(_RadioLost(self))
            app.add_listener(self._scene)
            app.add_listener(self._doors)

    def _stopped(self) -> asyncio.Future[None]:
        assert self._loop is not None
        self._stay = self._loop.create_future()
        return self._stay

    async def _list_contacts(self) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for device in (getattr(self._app, "devices", {}) or {}).values():
            if not looks_like_contact(device):
                continue
            model = ""
            try:
                model = str(getattr(device, "model", "") or "").replace("\x00", "").strip()
            except Exception:  # noqa: BLE001
                model = ""
            found.append({"ieee": str(getattr(device, "ieee", "") or ""), "model": model})
        return [item for item in found if item["ieee"]]

    async def _list_remotes(self) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for device in (getattr(self._app, "devices", {}) or {}).values():
            if not looks_like_scene_remote(device):
                continue
            model = ""
            try:
                model = str(getattr(device, "model", "") or "").replace("\x00", "").strip()
            except Exception:  # noqa: BLE001
                model = ""
            found.append({"ieee": str(getattr(device, "ieee", "") or ""), "model": model})
        return [item for item in found if item["ieee"]]

    async def _permit(self, seconds: int) -> None:
        await self._app.permit(seconds)
        print(f"Zigbee permit join for {seconds}s")

    async def _current_on(self, ieee: str | None) -> bool | None:
        matches = _light_endpoints(self._app)
        if ieee:
            targeted = [
                item for item in matches if str(item[0].ieee).lower() == ieee.lower()
            ]
            if targeted:
                matches = targeted
        if not matches:
            return None
        _device, endpoint = matches[0]
        try:
            cluster = endpoint.in_clusters[ON_OFF_CLUSTER]
            result = await cluster.read_attributes(["on_off"])
            values = result[0] if isinstance(result, tuple) else result
            value = values.get("on_off")
        except Exception as exc:  # noqa: BLE001
            print(f"Zigbee light state unread: {exc}")
            return None
        if value is None:
            return None
        return bool(value)

    async def _list(self) -> list[dict[str, str]]:
        lights = []
        for device, _endpoint in _light_endpoints(self._app):
            lights.append({"ieee": str(device.ieee), "name": _device_name(device)})
        return lights

    async def _set_on(self, turn_on: bool, ieee: str | None) -> dict[str, Any]:
        target_ieee = ieee or config.DOOR_LIGHT or None
        matches = _light_endpoints(self._app)
        if target_ieee:
            targeted = [(device, endpoint) for device, endpoint in matches if str(device.ieee).lower() == target_ieee.lower()]
            if targeted:
                matches = targeted
            elif ieee:
                raise LookupError(f"Zigbee bulb {ieee} is not paired")
        if not matches:
            raise LookupError("No Zigbee bulb is paired")
        state = "on" if turn_on else "off"
        reached: list[str] = []
        missed: list[str] = []

        async def _send_one(device: Any, endpoint: Any) -> tuple[str, bool, BaseException | None]:
            try:
                cluster = endpoint.in_clusters[ON_OFF_CLUSTER]
                command = getattr(cluster, "on" if turn_on else "off", None)
                if command is None:
                    await cluster.command(0x01 if turn_on else 0x00)
                else:
                    await command()
                print(f"Zigbee light {device.ieee} {state}")
                return str(device.ieee), True, None
            except Exception as exc:  # noqa: BLE001
                print(f"Zigbee light {device.ieee} {state} failed: {exc}")
                return str(device.ieee), False, exc

        results = await asyncio.gather(*[_send_one(d, ep) for d, ep in matches])
        dead: BaseException | None = None
        for dev_ieee, ok, failure in results:
            if ok:
                reached.append(dev_ieee)
            else:
                missed.append(dev_ieee)
                if failure is not None and _port_is_gone(failure):
                    dead = failure

        if dead is not None:
            self._on_radio_lost(dead)
        if not reached:
            raise RuntimeError(f"No bulb acknowledged the {state} command")
        self._remember(turn_on)
        return {
            "ieee": reached[0],
            "name": "Zigbee bulb",
            "state": f"{state}, {len(reached)} of {len(matches)}",
            "reached": reached,
            "missed": missed,
        }


class _RadioLost:
    """zigpy calls connection_lost when the coordinator stick disappears."""

    def __init__(self, lights: ZigbeeLights) -> None:
        self._lights = lights

    def connection_lost(self, exc: BaseException) -> None:
        self._lights._on_radio_lost(exc)


def _port_is_gone(exc: BaseException) -> bool:
    if isinstance(exc, AttributeError):
        return True
    text = str(exc).lower()
    return any(word in text for word in ("disconnect", "serial", "ttyusb", "input/output", "no such file"))


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
