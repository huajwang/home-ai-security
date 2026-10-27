"""Zigbee door and window contact on the same coordinator as the bulbs.

The paired sensor is a Tuya TS0203 (model ZD06). It sleeps until the
magnet moves, then sends an IAS Zone status. Alarm bit 0 means the
contact is open. The coordinator has to answer the enroll request and
write its own IEEE as the CIE address before later reports arrive.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Any

IAS_ZONE_CLUSTER = 0x0500
ZONE_STATUS_ATTR = 0x0002
ALARM_OPEN = 0x0001
ACTOR = "door-sensor"
# Reed chatter is a second report within a fraction of a second. A real
# open or close after that is shown immediately.
BOUNCE_SECONDS = 0.4
CONFIRM_AFTER = 1.0
_REPORT_SIZE = {
    0x10: 1,
    0x18: 1,
    0x20: 1,
    0x30: 1,
    0x19: 2,
    0x21: 2,
    0x29: 2,
    0x31: 2,
}


class DoorContacts:
    """Remember each sensor's latest open or closed state."""

    def __init__(self, bus: Any, store: Any, lights: Any = None, bounce: float = BOUNCE_SECONDS) -> None:
        self._bus = bus
        self._store = store
        self._lights = lights
        self._bounce = bounce
        self._lock = threading.Lock()
        self._open: dict[str, bool] = {}
        self._seen_at: dict[str, str] = {}
        self._models: dict[str, str] = {}
        self._edge_at: dict[str, float] = {}
        self._pending: dict[str, tuple[bool, str, float]] = {}
        self._timers: dict[str, threading.Timer] = {}

    def submit(self, ieee: str, opened: bool, model: str = "", confirmed: bool = False) -> None:
        """Show a quiet change at once. Hold only a fast reversal from reed chatter."""
        ieee = str(ieee or "")
        if not ieee:
            return
        opened = bool(opened)
        now = time.monotonic()
        publish = False
        with self._lock:
            if model:
                self._models[ieee] = model
            if confirmed:
                self._clear_pending(ieee)
                self._edge_at[ieee] = now
                publish = True
            else:
                shown = self._open.get(ieee)
                edged = self._edge_at.get(ieee)
                recent = edged is not None and now - edged < self._bounce
                if self._pending.get(ieee) is None and shown is opened:
                    return
                if self._pending.get(ieee) is None and not recent:
                    self._edge_at[ieee] = now
                    publish = True
                elif shown is opened:
                    self._clear_pending(ieee)
                    return
                else:
                    token = now
                    self._pending[ieee] = (opened, model, token)
                    self._arm(ieee, token)
        if publish:
            self.handle(ieee, opened, model)

    def _arm(self, ieee: str, token: float) -> None:
        previous = self._timers.get(ieee)
        if previous is not None:
            previous.cancel()
        timer = threading.Timer(self._bounce, self._commit, args=(ieee, token))
        timer.daemon = True
        self._timers[ieee] = timer
        timer.start()

    def _clear_pending(self, ieee: str) -> None:
        self._pending.pop(ieee, None)
        timer = self._timers.pop(ieee, None)
        if timer is not None:
            timer.cancel()

    def _commit(self, ieee: str, token: float) -> None:
        with self._lock:
            pending = self._pending.get(ieee)
            if pending is None or pending[2] != token:
                return
            opened, model, _token = pending
            self._pending.pop(ieee, None)
            self._timers.pop(ieee, None)
            self._edge_at[ieee] = time.monotonic()
        self.handle(ieee, opened, model)

    def handle(self, ieee: str, opened: bool, model: str = "") -> str | None:
        ieee = str(ieee or "")
        if not ieee:
            return None
        with self._lock:
            if model:
                self._models[ieee] = model
            if self._open.get(ieee) is opened:
                return None
            self._open[ieee] = opened
        label = "door opened" if opened else "door closed"
        event_body: dict[str, Any] = {"label": label, "confidence": 1.0, "camera": "door-sensor"}
        if self._store is not None:
            event = self._store.add_event(label, 1.0, None, camera="door-sensor")
            event_body = {
                "id": event["id"],
                "ts": event["ts"],
                "label": event["label"],
                "confidence": event["confidence"],
                "camera": event.get("camera"),
            }
            with self._lock:
                self._seen_at[ieee] = str(event["ts"])
        else:
            with self._lock:
                self._seen_at[ieee] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._publish(
            {
                "type": "contact_changed",
                "ieee": ieee,
                "open": opened,
                "name": "Door",
                "actor": ACTOR,
                "event": event_body,
            }
        )
        print(f"Door sensor {ieee}: {label}")
        return label

    def status(self) -> dict[str, Any]:
        discovered: list[dict[str, str]] = []
        lights = self._lights
        if lights is not None and hasattr(lights, "list_contacts"):
            try:
                discovered = list(lights.list_contacts())
            except Exception as exc:  # noqa: BLE001
                print(f"Door sensor list failed: {exc}")
        with self._lock:
            by_ieee: dict[str, dict[str, Any]] = {}
            for item in discovered:
                ieee = str(item.get("ieee") or "")
                if not ieee:
                    continue
                by_ieee[ieee] = {
                    "ieee": ieee,
                    "model": str(item.get("model") or self._models.get(ieee) or ""),
                }
            for ieee, opened in self._open.items():
                slot = by_ieee.setdefault(ieee, {"ieee": ieee, "model": self._models.get(ieee, "")})
                slot["open"] = opened
                slot["updated_at"] = self._seen_at.get(ieee)
            for ieee, slot in by_ieee.items():
                slot.setdefault("open", self._open.get(ieee))
                slot.setdefault("updated_at", self._seen_at.get(ieee))
                slot.setdefault("model", self._models.get(ieee, ""))
            ordered = [by_ieee[key] for key in sorted(by_ieee)]
        for index, slot in enumerate(ordered):
            slot["name"] = "Door" if len(ordered) == 1 else f"Door {index + 1}"
        return {"contacts": ordered}

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


class DoorRadio:
    """Listen for IAS Zone contact frames and enroll the sensor once."""

    def __init__(self, lights: Any) -> None:
        self._lights = lights
        self._enrolled: set[str] = set()
        self._enrolling: set[str] = set()
        self._confirm_gen: dict[str, int] = {}

    def packet_received(self, packet: Any) -> None:
        try:
            self._on_packet(packet)
        except Exception as exc:  # noqa: BLE001
            print(f"Door sensor frame ignored: {exc}")

    def handle_message(
        self,
        device: Any,
        _profile_id: int,
        cluster_id: int,
        src_ep: int,
        _dst_ep: int,
        data: Any,
    ) -> None:
        try:
            self._on_message(device, int(cluster_id), int(src_ep), _frame_bytes(data))
        except Exception as exc:  # noqa: BLE001
            print(f"Door sensor frame ignored: {exc}")

    def device_initialized(self, device: Any) -> None:
        if looks_like_contact(device):
            self._schedule_enroll(device)

    def _on_packet(self, packet: Any) -> None:
        app = getattr(self._lights, "_app", None)
        device = _find_device(app, packet)
        cluster = getattr(packet, "cluster_id", None)
        endpoint = getattr(packet, "src_ep", None)
        if device is None or cluster is None or endpoint is None:
            return
        self._on_message(device, int(cluster), int(endpoint), _frame_bytes(getattr(packet, "data", b"")))

    def _on_message(self, device: Any, cluster_id: int, src_ep: int, payload: bytes) -> None:
        if not looks_like_contact(device):
            return
        if cluster_id == IAS_ZONE_CLUSTER:
            print(f"Door sensor raw ep={src_ep} cluster={cluster_id:#06x} data={payload.hex()}")
        parsed = contact_from_zcl(cluster_id, payload)
        if parsed is None:
            self._schedule_enroll(device)
            return
        kind, opened = parsed
        if kind == "status" and opened is not None:
            self._lights.note_contact(str(getattr(device, "ieee", "") or ""), opened, _model(device))
            self._schedule_confirm(device)
        self._schedule_enroll(device)

    def _schedule_enroll(self, device: Any) -> None:
        ieee = str(getattr(device, "ieee", "") or "")
        if not ieee or ieee in self._enrolled or ieee in self._enrolling:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._enrolling.add(ieee)
        loop.create_task(self._enroll(device))

    def _schedule_confirm(self, device: Any) -> None:
        ieee = str(getattr(device, "ieee", "") or "")
        if not ieee:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._confirm_gen[ieee] = self._confirm_gen.get(ieee, 0) + 1
        generation = self._confirm_gen[ieee]
        loop.call_later(CONFIRM_AFTER, self._kick_confirm, device, generation)

    def _kick_confirm(self, device: Any, generation: int) -> None:
        asyncio.create_task(self._confirm(device, generation))

    async def _confirm(self, device: Any, generation: int) -> None:
        ieee = str(getattr(device, "ieee", "") or "")
        if self._confirm_gen.get(ieee) != generation:
            return
        cluster = _ias_cluster(device)
        if cluster is None:
            return
        try:
            result = await cluster.read_attributes(["zone_status"])
        except Exception as exc:  # noqa: BLE001
            print(f"Door sensor {ieee} confirm will retry: {exc}")
            return
        if self._confirm_gen.get(ieee) != generation:
            return
        values = result[0] if isinstance(result, tuple) else result
        status = (values or {}).get("zone_status")
        if status is None:
            return
        self._lights.note_contact(ieee, bool(int(status) & ALARM_OPEN), _model(device), confirmed=True)

    async def _enroll(self, device: Any) -> None:
        ieee = str(getattr(device, "ieee", "") or "")
        try:
            cluster = _ias_cluster(device)
            if cluster is None:
                return
            cie = _coordinator_ieee(device)
            if cie is not None:
                await cluster.write_attributes({"cie_addr": cie})
            await cluster.enroll_response(0, 1)
            result = await cluster.read_attributes(["zone_status"])
            values = result[0] if isinstance(result, tuple) else result
            status = (values or {}).get("zone_status")
            if status is not None:
                self._lights.note_contact(ieee, bool(int(status) & ALARM_OPEN), _model(device), confirmed=True)
            self._enrolled.add(ieee)
            print(f"Door sensor {ieee} is ready")
        except Exception as exc:  # noqa: BLE001
            print(f"Door sensor {ieee} setup will retry: {exc}")
        finally:
            self._enrolling.discard(ieee)


def contact_from_zcl(cluster_id: int, data: bytes) -> tuple[str, bool | None] | None:
    """Decode an IAS Zone frame. ('status', open) or ('enroll', None)."""
    if int(cluster_id) != IAS_ZONE_CLUSTER:
        return None
    parsed = _zcl(data)
    if parsed is None:
        return None
    frame, _tsn, command, payload = parsed
    frame_type = frame & 0x03
    if frame_type == 0x01 and command == 0x00 and len(payload) >= 2:
        status = int.from_bytes(payload[:2], "little")
        return ("status", bool(status & ALARM_OPEN))
    if frame_type == 0x01 and command == 0x01:
        return ("enroll", None)
    if frame_type == 0x00 and command == 0x0A:
        opened = _reported_zone_status(payload)
        if opened is None:
            return None
        return ("status", opened)
    return None


def looks_like_contact(device: Any) -> bool:
    if device is None or getattr(device, "nwk", None) in (0, 0x0000):
        return False
    if _model(device).upper().startswith("TS0203"):
        return True
    return _ias_cluster(device) is not None


def _model(device: Any) -> str:
    try:
        raw = getattr(device, "model", "") or ""
    except Exception:  # noqa: BLE001
        return ""
    return str(raw).replace("\x00", "").strip()


def _ias_cluster(device: Any) -> Any:
    for ep_id, endpoint in (getattr(device, "endpoints", {}) or {}).items():
        if ep_id in (0, None):
            continue
        clusters = getattr(endpoint, "in_clusters", {}) or {}
        for key in (IAS_ZONE_CLUSTER, str(IAS_ZONE_CLUSTER)):
            cluster = clusters.get(key)
            if cluster is not None:
                return cluster
    return None


def _coordinator_ieee(device: Any) -> Any:
    app = getattr(device, "application", None)
    state = getattr(app, "state", None)
    node = getattr(state, "node_info", None)
    ieee = getattr(node, "ieee", None)
    if ieee is not None:
        return ieee
    return getattr(app, "ieee", None)


def _reported_zone_status(payload: bytes) -> bool | None:
    index = 0
    found: bool | None = None
    while index + 3 <= len(payload):
        attr = int.from_bytes(payload[index : index + 2], "little")
        datatype = payload[index + 2]
        index += 3
        size = _REPORT_SIZE.get(datatype)
        if size is None or index + size > len(payload):
            return found
        if attr == ZONE_STATUS_ATTR:
            found = bool(int.from_bytes(payload[index : index + size], "little") & ALARM_OPEN)
        index += size
    return found


def _zcl(data: bytes) -> tuple[int, int, int, bytes] | None:
    if len(data) < 3:
        return None
    frame = data[0]
    if (frame & 0x03) > 0x01:
        return None
    index = 3 if frame & 0x04 else 1
    if len(data) < index + 2:
        return None
    return frame, data[index], data[index + 1], data[index + 2 :]


def _frame_bytes(data: Any) -> bytes:
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    serialize = getattr(data, "serialize", None)
    if callable(serialize):
        return bytes(serialize())
    return bytes(data)


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
    return None
