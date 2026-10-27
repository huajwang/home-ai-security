"""Four-button Zigbee 3.0 scene remote on the same coordinator as the bulbs.

The wand runs on an LR23A battery. Hold button 1 for 10 seconds until
the LEDs flash quickly to pair it. Each button has three gestures:
single click, double click, and a 5-second hold.

Button 1's click toggles arm and disarm. While an alarm is showing,
that click silences it and leaves the system disarmed. Button 2's click
toggles the Zigbee light. A 5-second hold of button 4 raises a panic.
The Elegoo siren sounds for that event, armed or not.

These wands report like a Tuya TS0044. Each button is its own endpoint.
Command 0xFD on the On/Off cluster carries the gesture: 0 single, 1
double, 2 hold. Some firmware sends a plain on, off, or toggle, or a
level step or move, instead.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

ON_OFF_CLUSTER = 0x0006
LEVEL_CLUSTER = 0x0008
COLOR_CLUSTER = 0x0300
TUYA_PRESS = 0xFD
ACTION_GAP_SECONDS = 1.0
ACTOR = "scene-remote"

# Tuya command 0xFD payload.
_TUYA_KIND = {0: "single", 1: "double", 2: "hold"}
# Plain On/Off commands used when the remote is in command mode.
_ONOFF_KIND = {0x00: "double", 0x01: "single", 0x02: "hold"}
# Level Control: step is a click, move is a hold. Stop is a release.
_LEVEL_KIND = {0x01: "hold", 0x02: "single", 0x05: "hold", 0x06: "single"}


@dataclass(frozen=True)
class ButtonPress:
    button: int
    kind: str
    ieee: str = ""
    tsn: int | None = None


class SceneRemote:
    """Map one remote onto arm, light, and panic."""

    def __init__(
        self,
        state: Any,
        bus: Any,
        store: Any,
        lights: Any,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._state = state
        self._bus = bus
        self._store = store
        self._lights = lights
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._seen: dict[tuple[Any, ...], float] = {}
        self._acted: dict[tuple[Any, ...], float] = {}

    def handle(self, press: ButtonPress) -> str | None:
        with self._lock:
            if not self._accept(press):
                return None
        action = self._dispatch(press)
        if action is None:
            print(f"Scene remote button {press.button} {press.kind}")
            return None
        print(f"Scene remote button {press.button} {press.kind}: {action}")
        return action

    def _accept(self, press: ButtonPress) -> bool:
        now = self._clock()
        self._seen = {key: seen for key, seen in self._seen.items() if now - seen < 30}
        if press.tsn is not None:
            key = (press.ieee, press.button, press.kind, press.tsn)
            if key in self._seen:
                return False
            self._seen[key] = now
        action_key = (press.ieee, press.button, press.kind)
        previous = self._acted.get(action_key)
        if previous is not None and now - previous < ACTION_GAP_SECONDS:
            return False
        self._acted[action_key] = now
        return True

    def _dispatch(self, press: ButtonPress) -> str | None:
        if press.button == 1 and press.kind == "single":
            return self._toggle_arm()
        if press.button == 2 and press.kind == "single":
            return self._toggle_light()
        if press.button == 4 and press.kind == "hold":
            return self._panic()
        return None

    def _toggle_arm(self) -> str:
        snap = self._state.snapshot()
        armed = False if snap["alarm_active"] else (not snap["armed"])
        changed = self._state.set_armed(armed)
        if snap["alarm_active"]:
            self._publish({"type": "alarm_cleared", "actor": ACTOR})
        if changed:
            self._publish({"type": "armed_changed", "armed": armed, "actor": ACTOR})
        return "arm" if armed else "disarm"

    def _toggle_light(self) -> str:
        lights = self._lights
        if lights is None:
            raise RuntimeError("Light controller is not available")
        toggle = getattr(lights, "toggle", None)
        if toggle is not None:
            result = toggle()
            state = str(result.get("state", "")) if isinstance(result, dict) else ""
            return "light_on" if state.startswith("on") else "light_off"
        turn_on = not bool(lights.is_on())
        lights.set_on(turn_on)
        return "light_on" if turn_on else "light_off"

    def _panic(self) -> str:
        self._state.set_alarm(True, source="remote")
        event_body: dict[str, Any] = {
            "label": "panic",
            "confidence": 1.0,
            "camera": "remote",
        }
        if self._store is not None:
            event = self._store.add_event("panic", 1.0, None, camera="remote")
            event_body = {
                "id": event["id"],
                "ts": event["ts"],
                "label": event["label"],
                "confidence": event["confidence"],
                "camera": event.get("camera"),
            }
        self._publish({"type": "panic", "actor": ACTOR, "event": event_body})
        return "panic"

    def _publish(self, payload: dict[str, Any]) -> None:
        bus = self._bus
        if bus is None:
            return
        if hasattr(bus, "publish_threadsafe"):
            bus.publish_threadsafe(payload)
            return
        publish = getattr(bus, "publish", None)
        if publish is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(publish(payload))


class SceneRadio:
    """Listen on the coordinator for scene-remote frames."""

    def __init__(self, lights: Any) -> None:
        self._lights = lights
        self._spelled: set[str] = set()
        self._spelling: set[str] = set()

    def packet_received(self, packet: Any) -> None:
        try:
            self._on_packet(packet)
        except Exception as exc:  # noqa: BLE001
            print(f"Scene remote frame ignored: {exc}")

    def handle_message(
        self,
        device: Any,
        _profile_id: int,
        cluster_id: int,
        src_ep: int,
        _dst_ep: int,
        data: Any,
    ) -> None:
        """zigpy on the ROCK notifies listeners with this, not packet_received."""
        try:
            self._on_message(device, cluster_id, src_ep, data)
        except Exception as exc:  # noqa: BLE001
            print(f"Scene remote frame ignored: {exc}")

    def device_initialized(self, device: Any) -> None:
        self.consider(device)

    def consider(self, device: Any) -> None:
        """Ask a newly joined remote to report presses. Asleep devices retry later."""
        if not looks_like_scene_remote(device):
            return
        ieee = str(getattr(device, "ieee", "") or "")
        if not ieee or ieee in self._spelled or ieee in self._spelling:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._spelling.add(ieee)
        loop.create_task(self._spell(device))

    async def _spell(self, device: Any) -> None:
        # Reading these Basic attributes is the Tuya wake-up used by ZHA.
        # The remote answers while it is awake from pairing or a press.
        ieee = str(getattr(device, "ieee", "") or "")
        try:
            endpoints = getattr(device, "endpoints", {}) or {}
            endpoint = endpoints.get(1)
            clusters = getattr(endpoint, "in_clusters", {}) if endpoint is not None else None
            basic = (clusters or {}).get(0)
            if basic is None:
                return
            await basic.read_attributes([4, 0, 1, 5, 7, 0xFFFE])
            self._spelled.add(ieee)
            print(f"Scene remote {ieee} is ready")
        except Exception as exc:  # noqa: BLE001
            print(f"Scene remote {ieee} setup will retry: {exc}")
        finally:
            self._spelling.discard(ieee)

    def _on_packet(self, packet: Any) -> None:
        app = getattr(self._lights, "_app", None)
        press = decode_button(packet, app)
        if press is not None:
            self._lights.note_button(press)
        device = _find_device(app, packet)
        if device is not None:
            self.consider(device)

    def _on_message(self, device: Any, cluster_id: int, src_ep: int, data: Any) -> None:
        if getattr(device, "nwk", None) in (0, 0x0000):
            return
        payload = _frame_bytes(data)
        if looks_like_scene_remote(device):
            print(
                f"Scene remote raw ep={int(src_ep)} cluster={int(cluster_id):#06x} "
                f"data={payload.hex()}"
            )
        parsed = press_from_zcl(
            int(cluster_id),
            int(src_ep),
            payload,
            remote=looks_like_scene_remote(device),
        )
        if parsed is None:
            if looks_like_scene_remote(device) and int(cluster_id) in {ON_OFF_CLUSTER, LEVEL_CLUSTER}:
                print(
                    f"Scene remote frame ep={int(src_ep)} cluster={int(cluster_id):#06x} "
                    f"data={payload.hex()}"
                )
            return
        button, kind, tsn = parsed
        press = ButtonPress(button=button, kind=kind, ieee=str(getattr(device, "ieee", "") or ""), tsn=tsn)
        self._lights.note_button(press)
        self.consider(device)


def decode_button(packet: Any, app: Any) -> ButtonPress | None:
    nwk = _source_nwk(packet)
    if nwk == 0:
        return None
    cluster = getattr(packet, "cluster_id", None)
    endpoint = getattr(packet, "src_ep", None)
    if cluster is None or endpoint is None:
        return None
    try:
        cluster_id = int(cluster)
        endpoint_id = int(endpoint)
        data = _frame_bytes(getattr(packet, "data", b""))
    except (TypeError, ValueError):
        return None
    device = _find_device(app, packet)
    if getattr(device, "nwk", None) in (0, 0x0000):
        return None
    parsed = press_from_zcl(
        cluster_id,
        endpoint_id,
        data,
        remote=looks_like_scene_remote(device),
    )
    if parsed is None:
        return None
    button, kind, tsn = parsed
    ieee = str(getattr(device, "ieee", "") or "")
    if not ieee and nwk is not None:
        ieee = f"{nwk:04x}"
    return ButtonPress(button=button, kind=kind, ieee=ieee, tsn=tsn)


def press_from_zcl(
    cluster_id: int,
    endpoint: int,
    data: bytes,
    *,
    remote: bool,
) -> tuple[int, str, int] | None:
    parsed = zcl_cluster_command(data)
    if parsed is None or not 1 <= endpoint <= 4:
        return None
    tsn, command_id, payload = parsed
    if cluster_id == ON_OFF_CLUSTER and command_id == TUYA_PRESS and payload:
        kind = _TUYA_KIND.get(payload[0])
        if kind is None:
            return None
        return endpoint, kind, tsn
    if not remote:
        return None
    if cluster_id == ON_OFF_CLUSTER:
        kind = _ONOFF_KIND.get(command_id)
        if kind is None:
            return None
        return endpoint, kind, tsn
    if cluster_id == LEVEL_CLUSTER:
        kind = _LEVEL_KIND.get(command_id)
        if kind is None:
            return None
        return endpoint, kind, tsn
    return None


def zcl_cluster_command(data: bytes) -> tuple[int, int, bytes] | None:
    """Return tsn, command id, and payload for a client-to-server cluster command."""
    if len(data) < 3:
        return None
    frame = data[0]
    if (frame & 0x03) != 0x01 or frame & 0x08:
        return None
    index = 3 if frame & 0x04 else 1
    if frame & 0x04 and len(data) < 5:
        return None
    if len(data) < index + 2:
        return None
    return data[index], data[index + 1], data[index + 2 :]


def looks_like_scene_remote(device: Any) -> bool:
    if device is None or getattr(device, "nwk", None) in (0, 0x0000):
        return False
    on_off_endpoints = 0
    for ep_id, endpoint in (getattr(device, "endpoints", {}) or {}).items():
        if ep_id in (0, None):
            continue
        clusters: set[int] = set()
        for group in ("in_clusters", "out_clusters"):
            for key in (getattr(endpoint, group, {}) or {}).keys():
                try:
                    clusters.add(int(key))
                except (TypeError, ValueError):
                    continue
        if COLOR_CLUSTER in clusters:
            return False
        if ON_OFF_CLUSTER in clusters:
            on_off_endpoints += 1
    model = str(getattr(device, "model", "") or "").upper().replace("\x00", "").strip()
    if model.startswith("TS004"):
        return True
    return on_off_endpoints >= 2


def _source_nwk(packet: Any) -> int | None:
    src = getattr(packet, "src", None)
    if src is None:
        return None
    mode = getattr(src, "addr_mode", None)
    if mode is not None and "IEEE" in str(getattr(mode, "name", mode)).upper():
        return None
    address = getattr(src, "address", None)
    if not isinstance(address, int) or isinstance(address, bool):
        return None
    if address < 0 or address > 0xFFFF:
        return None
    return address


def _find_device(app: Any, packet: Any) -> Any:
    if app is None:
        return None
    src = getattr(packet, "src", None)
    address = getattr(src, "address", None)
    for device in (getattr(app, "devices", {}) or {}).values():
        if address is not None and getattr(device, "nwk", None) == address:
            return device
        if address is not None and getattr(device, "ieee", None) == address:
            return device
    getter = getattr(app, "get_device", None)
    if getter is None or address is None:
        return None
    for key in ("nwk", "ieee"):
        try:
            return getter(**{key: address})
        except Exception:  # noqa: BLE001
            continue
    return None


def _frame_bytes(data: Any) -> bytes:
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    serialize = getattr(data, "serialize", None)
    if callable(serialize):
        return bytes(serialize())
    return bytes(data)
