"""Plain-language search over stored events. No language model and no video."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ["HUB_VISION_ENABLED"] = "0"
os.environ["HUB_AUDIO_ENABLED"] = "0"
os.environ["HUB_DOORBELL_ENABLED"] = "0"
os.environ["HUB_TALKBACK_ENABLED"] = "0"
os.environ["HUB_CAMERA_URL"] = ""
os.environ["HUB_DRIVEWAY_CAMERA"] = ""
os.environ["HUB_MONITOR"] = "0"
os.environ["HUB_PC_CAMERA"] = "0"
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_data")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

from fastapi.testclient import TestClient

from hub.app import create_app
from hub.search.query import parse_question

_EASTERN = timezone(timedelta(hours=-4))
_NOW = datetime(2026, 10, 3, 15, 0, tzinfo=_EASTERN)


def test_person_at_the_door_yesterday_afternoon() -> None:
    parsed = parse_question("person at the door yesterday afternoon", _NOW)
    assert parsed.understood is True
    assert parsed.label == "person"
    assert parsed.camera == "door"
    assert parsed.start == "2026-10-02T16:00:00+00:00"
    assert parsed.end == "2026-10-02T21:00:00+00:00"


def test_car_in_the_driveway_sunday() -> None:
    parsed = parse_question("car in the driveway Sunday", _NOW)
    assert parsed.understood is True
    assert parsed.label == "car"
    assert parsed.camera == "driveway"
    assert parsed.start == "2026-09-27T04:00:00+00:00"
    assert parsed.end == "2026-09-28T04:00:00+00:00"


def test_delivery_driver_is_not_a_stored_label() -> None:
    parsed = parse_question("delivery driver on Sunday afternoon", _NOW)
    assert parsed.understood is False
    assert parsed.label is None


def test_search_finds_a_car_recorded_today() -> None:
    with TestClient(create_app()) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "username": "owner",
                "password": "changeme",
                "device_name": "search",
                "device_role": "phone",
            },
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.app.state.store.add_event("car", 0.8, None, camera="driveway")
        found = client.get("/v1/events/search", params={"q": "car in the driveway today"}, headers=headers)
        assert found.status_code == 200, found.text
        body = found.json()
        assert body["filter"]["label"] == "car"
        assert body["filter"]["camera"] == "driveway"
        assert len(body["events"]) == 1
        assert body["events"][0]["label"] == "car"
        assert body["events"][0]["camera"] == "driveway"

        missed = client.get(
            "/v1/events/search",
            params={"q": "delivery driver on Sunday afternoon"},
            headers=headers,
        )
        assert missed.status_code == 200
        assert missed.json()["events"] == []
        assert missed.json()["filter"]["understood"] is False
