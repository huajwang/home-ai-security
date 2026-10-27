"""The Zigbee door sensor reports opened and closed without raising an alarm."""

import time

from hub.devices.door_sensor import DoorContacts, DoorRadio, contact_from_zcl, looks_like_contact
from hub.devices.zigbee_light import ZigbeeLights
from hub.state import HubState
from hub.storage import Store


class _Bus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish_threadsafe(self, payload: dict) -> None:
        self.events.append(payload)


class _Endpoint:
    def __init__(self, clusters: dict[int, object]) -> None:
        self.in_clusters = clusters
        self.out_clusters: dict[int, object] = {}


class _Device:
    def __init__(self, model: str, clusters: dict[int, object], nwk: int = 7069) -> None:
        self.model = model
        self.nwk = nwk
        self.ieee = "a4:c1:38:40:26:0c:34:84"
        self.endpoints = {1: _Endpoint(clusters)}


def test_zone_status_bit_means_open():
    opened = bytes([0x19, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])
    closed = bytes([0x09, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert contact_from_zcl(0x0500, opened) == ("status", True)
    assert contact_from_zcl(0x0500, closed) == ("status", False)


def test_enroll_request_is_not_a_contact_change():
    frame = bytes([0x19, 0x03, 0x01, 0x15, 0x00, 0x41, 0x11])
    assert contact_from_zcl(0x0500, frame) == ("enroll", None)


def test_attribute_report_carries_zone_status():
    frame = bytes([0x18, 0x04, 0x0A, 0x02, 0x00, 0x19, 0x01, 0x00])
    assert contact_from_zcl(0x0500, frame) == ("status", True)


def test_a_light_frame_is_not_a_door():
    assert contact_from_zcl(0x0006, bytes([0x01, 0x01, 0x01])) is None
    bulb = _Device("E11-G13", {0x0006: object(), 0x0300: object()})
    remote = _Device("TS0044", {0x0006: object()})
    sensor = _Device("TS0203", {0x0500: object()})
    assert looks_like_contact(bulb) is False
    assert looks_like_contact(remote) is False
    assert looks_like_contact(sensor) is True


def test_open_then_close_is_stored_once_each(tmp_path):
    store = Store(tmp_path / "hub.db")
    bus = _Bus()
    doors = DoorContacts(bus, store)
    assert doors.handle("a4:c1:38:40:26:0c:34:84", True, "TS0203") == "door opened"
    assert doors.handle("a4:c1:38:40:26:0c:34:84", True, "TS0203") is None
    assert doors.handle("a4:c1:38:40:26:0c:34:84", False, "TS0203") == "door closed"
    labels = [event["label"] for event in store.list_events(None, 10)]
    assert labels == ["door closed", "door opened"]
    assert bus.events[0]["type"] == "contact_changed"
    assert bus.events[0]["open"] is True
    assert doors.status()["contacts"] == [
        {
            "ieee": "a4:c1:38:40:26:0c:34:84",
            "model": "TS0203",
            "open": False,
            "updated_at": bus.events[-1]["event"]["ts"],
            "name": "Door",
        }
    ]
    assert HubState().snapshot()["alarm_active"] is False


def test_handle_message_delivers_an_opened_contact():
    class _Lights:
        def __init__(self) -> None:
            self.notes: list[tuple[str, bool]] = []

        def note_contact(self, ieee: str, opened: bool, model: str = "") -> None:
            self.notes.append((ieee, opened))

    lights = _Lights()
    device = _Device("TS0203", {0x0500: object()})
    DoorRadio(lights).handle_message(
        device,
        260,
        0x0500,
        1,
        1,
        bytes([0x19, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00]),
    )
    assert lights.notes == [("a4:c1:38:40:26:0c:34:84", True)]


def test_a_quiet_change_shows_immediately(tmp_path):
    store = Store(tmp_path / "hub.db")
    bus = _Bus()
    doors = DoorContacts(bus, store, bounce=0.4)
    doors.submit("a4:c1:38:40:26:0c:34:84", True, "TS0203")
    labels = [event["label"] for event in store.list_events(None, 10)]
    assert labels == ["door opened"]
    assert doors.status()["contacts"][0]["open"] is True


def test_reed_chatter_settles_on_the_latest_report(tmp_path):
    store = Store(tmp_path / "hub.db")
    bus = _Bus()
    doors = DoorContacts(bus, store, bounce=0.05)
    doors.submit("a4:c1:38:40:26:0c:34:84", True, "TS0203")
    doors.submit("a4:c1:38:40:26:0c:34:84", False, "TS0203")
    assert [event["label"] for event in store.list_events(None, 10)] == ["door opened"]
    time.sleep(0.2)
    assert [event["label"] for event in store.list_events(None, 10)] == ["door closed", "door opened"]
    assert doors.status()["contacts"][0]["open"] is False


def test_a_later_change_is_not_held(tmp_path):
    store = Store(tmp_path / "hub.db")
    bus = _Bus()
    doors = DoorContacts(bus, store, bounce=0.05)
    doors.submit("a4:c1:38:40:26:0c:34:84", True, "TS0203")
    time.sleep(0.08)
    doors.submit("a4:c1:38:40:26:0c:34:84", False, "TS0203")
    assert [event["label"] for event in store.list_events(None, 10)] == ["door closed", "door opened"]
    assert doors.status()["contacts"][0]["open"] is False


def test_a_confirmed_reading_corrects_without_waiting(tmp_path):
    store = Store(tmp_path / "hub.db")
    doors = DoorContacts(_Bus(), store, bounce=0.4)
    doors.submit("a4:c1:38:40:26:0c:34:84", True, "TS0203")
    doors.submit("a4:c1:38:40:26:0c:34:84", False, "TS0203", confirmed=True)
    assert doors.status()["contacts"][0]["open"] is False
    assert [event["label"] for event in store.list_events(None, 10)] == ["door closed", "door opened"]


def test_note_contact_runs_the_handler_off_the_caller():
    lights = ZigbeeLights()
    seen: list[bool] = []
    lights.set_contact_handler(lambda ieee, opened, model="": seen.append(opened))
    lights.note_contact("a4:c1:38:40:26:0c:34:84", True, "TS0203")
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert seen == [True]
