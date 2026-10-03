"""The Elegoo siren sounds once for an armed person at the door."""

from hub.elegoo_alert import AlertDecider, should_sound


def test_sounds_only_for_armed_person_at_the_door():
    assert should_sound({"label": "person", "camera": "door"}, True)
    assert not should_sound({"label": "person", "camera": "door"}, False)
    assert not should_sound({"label": "person", "camera": "driveway"}, True)
    assert not should_sound({"label": "car", "camera": "driveway"}, True)
    assert not should_sound({"label": "doorbell", "camera": "door"}, True)


def test_startup_does_not_replay_old_events():
    decider = AlertDecider()
    old = [{"id": 1, "label": "person", "camera": "door"}]
    assert decider.commands(old, True) == []
    assert decider.commands(old, True) == []


def test_new_armed_visit_sends_one_on():
    decider = AlertDecider()
    decider.commands([], True)
    event = {"id": 4, "label": "person", "camera": "door"}
    assert decider.commands([event], True) == ["ON"]
    assert decider.commands([event], True) == []


def test_disarm_sends_off_and_a_driveway_event_does_not_sound():
    decider = AlertDecider()
    decider.commands([], True)
    driveway = {"id": 5, "label": "person", "camera": "driveway"}
    assert decider.commands([driveway], True) == []
    assert decider.commands([], False) == ["OFF"]
