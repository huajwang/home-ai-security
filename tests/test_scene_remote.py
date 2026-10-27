"""The 4-button Zigbee scene remote arms, toggles the light, and raises a panic."""

import time

from hub.devices.scene_remote import (
    ButtonPress,
    SceneRadio,
    SceneRemote,
    decode_button,
    looks_like_scene_remote,
)
from hub.devices.zigbee_light import ZigbeeLights
from hub.elegoo_alert import should_sound
from hub.state import HubState
from hub.storage import Store


class _Addr:
    def __init__(self, address: int) -> None:
        self.address = address


class _Packet:
    def __init__(self, data: bytes, ep: int = 1, cluster: int = 0x0006, nwk: int = 0x1234) -> None:
        self.data = data
        self.src_ep = ep
        self.cluster_id = cluster
        self.src = _Addr(nwk)


class _Endpoint:
    def __init__(self, clusters: dict[int, object]) -> None:
        self.in_clusters = clusters
        self.out_clusters: dict[int, object] = {}


class _Device:
    def __init__(self, model: str, endpoints: dict[int, _Endpoint], nwk: int = 0x1234) -> None:
        self.model = model
        self.nwk = nwk
        self.ieee = "00:11:22:33:44:55:66:77"
        self.endpoints = endpoints


class _App:
    def __init__(self, device: _Device) -> None:
        self.devices = {device.ieee: device}


class _Bus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish_threadsafe(self, payload: dict) -> None:
        self.events.append(payload)


class _Lights:
    def __init__(self) -> None:
        self.on = False
        self.calls: list[bool] = []

    def is_on(self) -> bool:
        return self.on

    def set_on(self, turn_on: bool, ieee: str | None = None) -> dict[str, str]:
        self.on = turn_on
        self.calls.append(turn_on)
        return {"state": "on" if turn_on else "off"}


class _ToggleLights:
    def __init__(self) -> None:
        self.on = False
        self.calls: list[bool] = []

    def toggle(self) -> dict[str, str]:
        self.on = not self.on
        self.calls.append(self.on)
        state = "on" if self.on else "off"
        return {"state": f"{state}, 1 of 1"}


def _remote(state: HubState | None = None, lights: _Lights | None = None, store: Store | None = None):
    state = state or HubState()
    bus = _Bus()
    lights = lights or _Lights()
    clock = [0.0]
    remote = SceneRemote(state, bus, store, lights, clock=lambda: clock[0])
    return remote, state, bus, lights, clock


def test_tuya_press_uses_the_endpoint_as_the_button():
    single = decode_button(_Packet(bytes([0x01, 0x11, 0xFD, 0x00]), ep=1), None)
    assert single is not None
    assert (single.button, single.kind, single.tsn) == (1, "single", 0x11)

    held = decode_button(_Packet(bytes([0x05, 0x02, 0x10, 0x2A, 0xFD, 0x02]), ep=4), None)
    assert held is not None
    assert (held.button, held.kind) == (4, "hold")

    double = decode_button(_Packet(bytes([0x01, 0x12, 0xFD, 0x01]), ep=2), None)
    assert double is not None
    assert double.kind == "double"


def test_plain_on_commands_come_from_a_remote_and_not_a_bulb():
    remote = _Device(
        "TS0044",
        {
            1: _Endpoint({0x0000: object(), 0x0006: object()}),
            2: _Endpoint({0x0006: object()}),
            3: _Endpoint({0x0006: object()}),
            4: _Endpoint({0x0006: object()}),
        },
    )
    bulb = _Device("TS0505", {1: _Endpoint({0x0006: object(), 0x0008: object(), 0x0300: object()})})
    frame = bytes([0x01, 0x22, 0x01])
    from_remote = decode_button(_Packet(frame, ep=2), _App(remote))
    assert from_remote is not None
    assert (from_remote.button, from_remote.kind) == (2, "single")
    assert decode_button(_Packet(frame, ep=1), _App(bulb)) is None
    assert decode_button(_Packet(bytes([0x01, 0x01, 0xFD, 0x02]), ep=4, nwk=0), None) is None
    assert not looks_like_scene_remote(bulb)
    assert looks_like_scene_remote(remote)


def test_level_hold_on_a_remote_endpoint_is_a_long_press():
    remote = _Device(
        "",
        {1: _Endpoint({0x0006: object()}), 4: _Endpoint({0x0006: object(), 0x0008: object()})},
    )
    frame = bytes([0x01, 0x33, 0x01])
    press = decode_button(_Packet(frame, ep=4, cluster=0x0008), _App(remote))
    assert press is not None
    assert (press.button, press.kind) == (4, "hold")


def test_button_1_toggles_arm_and_a_repeat_is_ignored():
    remote, state, bus, _lights, clock = _remote()
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=1)) == "arm"
    assert state.snapshot()["armed"] is True
    assert bus.events[-1]["type"] == "armed_changed"
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=1)) is None
    clock[0] = 0.2
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=2)) is None
    clock[0] = 2.0
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=3)) == "disarm"
    assert state.snapshot()["armed"] is False


def test_button_1_silences_a_panic_before_it_arms():
    remote, state, bus, _lights, clock = _remote()
    assert remote.handle(ButtonPress(4, "hold", ieee="aa", tsn=1)) == "panic"
    assert state.snapshot()["alarm_active"] is True
    assert state.snapshot()["armed"] is False
    clock[0] = 2.0
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=2)) == "disarm"
    assert state.snapshot()["alarm_active"] is False
    assert any(event["type"] == "alarm_cleared" for event in bus.events)
    clock[0] = 4.0
    assert remote.handle(ButtonPress(1, "single", ieee="aa", tsn=3)) == "arm"


def test_button_2_toggles_the_light_and_other_gestures_do_nothing():
    lights = _ToggleLights()
    remote, state, _bus, _lights, clock = _remote(lights=lights)
    assert remote.handle(ButtonPress(2, "single", ieee="aa", tsn=1)) == "light_on"
    assert lights.on is True
    clock[0] = 2.0
    assert remote.handle(ButtonPress(2, "single", ieee="aa", tsn=2)) == "light_off"
    assert lights.calls == [True, False]
    clock[0] = 4.0
    assert remote.handle(ButtonPress(2, "double", ieee="aa", tsn=3)) is None
    assert remote.handle(ButtonPress(3, "single", ieee="aa", tsn=4)) is None
    assert remote.handle(ButtonPress(4, "single", ieee="aa", tsn=5)) is None
    assert state.snapshot()["alarm_active"] is False
    assert lights.on is False


def test_button_2_uses_is_on_when_the_controller_has_no_toggle():
    remote, _state, _bus, lights, _clock = _remote()
    assert remote.handle(ButtonPress(2, "single", ieee="aa", tsn=8)) == "light_on"
    assert lights.on is True


def test_panic_is_stored_for_the_elegoo_siren(tmp_path):
    store = Store(tmp_path / "hub.db")
    remote, state, bus, _lights, _clock = _remote(store=store)
    assert remote.handle(ButtonPress(4, "hold", ieee="aa", tsn=9)) == "panic"
    event = store.list_events(None, 5)[0]
    assert event["label"] == "panic"
    assert event["camera"] == "remote"
    assert should_sound(event, False)
    assert state.set_alarm(False) is False
    assert state.snapshot()["alarm_active"] is True
    assert bus.events[-1]["type"] == "panic"
    assert state.set_armed(False) is False
    assert state.snapshot()["alarm_active"] is False


def test_a_camera_alarm_still_clears_when_the_person_leaves():
    state = HubState()
    assert state.set_alarm(True) is True
    assert state.set_alarm(False) is True
    assert state.snapshot()["alarm_active"] is False


def test_zigpy_handle_message_delivers_a_click():
    class _Device:
        nwk = 0x48A0
        ieee = "a4:c1:38:66:63:5f:14:1f"
        model = "TS0044"
        endpoints: dict = {}

    class _LightsSink:
        def __init__(self) -> None:
            self.presses: list[ButtonPress] = []

        def note_button(self, press: ButtonPress) -> None:
            self.presses.append(press)

    lights = _LightsSink()
    SceneRadio(lights).handle_message(_Device(), 260, 0x0006, 1, 1, bytes([0x01, 0x11, 0xFD, 0x00]))
    assert [(press.button, press.kind) for press in lights.presses] == [(1, "single")]


def test_radio_delivers_a_hold_to_the_light_controller():
    class _LightsSink:
        def __init__(self) -> None:
            self._app = None
            self.presses: list[ButtonPress] = []

        def note_button(self, press: ButtonPress) -> None:
            self.presses.append(press)

    lights = _LightsSink()
    SceneRadio(lights).packet_received(_Packet(bytes([0x01, 0x05, 0xFD, 0x02]), ep=4))
    assert [(press.button, press.kind) for press in lights.presses] == [(4, "hold")]


def test_note_button_runs_the_handler_off_the_caller():
    lights = ZigbeeLights()
    seen: list[int] = []
    lights.set_button_handler(lambda press: seen.append(press.button))
    lights.note_button(ButtonPress(1, "single", ieee="aa", tsn=1))
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert seen == [1]
    assert lights.status()["last_button"] == "1 single"
