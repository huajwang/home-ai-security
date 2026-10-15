"""Unit tests for face mask and covering detection."""

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
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_mask_data")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from hub.app import create_app
from hub.search.query import parse_question
from hub.vision.mask import detect_mask_heuristic, shared_mask_detector


def _make_synthetic_frame(face_type: str = "unmasked") -> tuple[np.ndarray, tuple[int, int, int, int]]:
    frame = np.zeros((300, 240, 3), dtype=np.uint8)
    frame[:] = (75, 75, 75)  # neutral gray background
    person_box = (40, 30, 180, 270)

    # Upper 35% of person is head: y in [30, 114], x centered in [61, 159]
    head_center_x, head_center_y = 110, 68
    cv2.ellipse(frame, (head_center_x, head_center_y), (36, 36), 0, 0, 360, (130, 160, 215), -1)  # skin tone

    if face_type == "blue_mask":
        # Surgical mask covering lower face (y from 68 to 105)
        cv2.rectangle(frame, (76, 68), (144, 105), (220, 180, 70), -1)
    elif face_type == "black_mask":
        # Dark/black cloth mask covering lower face
        cv2.rectangle(frame, (76, 68), (144, 105), (20, 20, 20), -1)
    elif face_type == "white_mask":
        # White / N95 mask covering lower face
        cv2.rectangle(frame, (76, 68), (144, 105), (240, 240, 240), -1)
    elif face_type == "balaclava":
        # Full dark covering over entire head with narrow eye slit
        cv2.ellipse(frame, (head_center_x, head_center_y), (36, 36), 0, 0, 360, (25, 25, 25), -1)
        cv2.rectangle(frame, (88, 52), (132, 62), (130, 160, 215), -1)

    return frame, person_box


def test_detect_unmasked_face() -> None:
    frame, box = _make_synthetic_frame("unmasked")
    result = detect_mask_heuristic(frame, box)
    assert result.masked is False
    assert result.status == "unmasked"
    assert result.confidence < 0.45


def test_detect_blue_surgical_mask() -> None:
    frame, box = _make_synthetic_frame("blue_mask")
    result = detect_mask_heuristic(frame, box)
    assert result.masked is True
    assert result.status == "masked"
    assert "blue" in result.details
    assert result.confidence >= 0.70


def test_detect_black_cloth_mask() -> None:
    frame, box = _make_synthetic_frame("black_mask")
    result = detect_mask_heuristic(frame, box)
    assert result.masked is True
    assert result.status == "masked"
    assert "mask" in result.details
    assert result.confidence >= 0.70


def test_detect_white_n95_mask() -> None:
    frame, box = _make_synthetic_frame("white_mask")
    result = detect_mask_heuristic(frame, box)
    assert result.masked is True
    assert result.status == "masked"
    assert result.confidence >= 0.60


def test_detect_balaclava_or_ski_mask() -> None:
    frame, box = _make_synthetic_frame("balaclava")
    result = detect_mask_heuristic(frame, box)
    assert result.masked is True
    assert result.status == "masked"
    assert result.confidence >= 0.70


def test_invalid_or_small_box() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = detect_mask_heuristic(frame, (10, 10, 18, 18))
    assert result.masked is False
    assert result.status == "unknown"


def test_query_parser_detects_mask_intent() -> None:
    eastern = timezone(timedelta(hours=-4))
    now = datetime(2026, 10, 15, 12, 0, tzinfo=eastern)

    q1 = parse_question("masked person at the door today", now)
    assert q1.understood is True
    assert q1.label == "person"
    assert q1.mask_detected is True

    q2 = parse_question("someone wearing a mask in the driveway", now)
    assert q2.understood is True
    assert q2.mask_detected is True

    q3 = parse_question("unmasked person at the door", now)
    assert q3.understood is True
    assert q3.mask_detected is False


def test_store_and_search_masked_events() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.store
        with store.cursor() as cur:
            cur.execute("DELETE FROM events")

        ev_unmasked = store.add_event("person", 0.91, None, camera="door", mask_detected=False)
        ev_masked = store.add_event("person", 0.95, None, camera="door", mask_detected=True)

        assert ev_unmasked["mask_detected"] == 0
        assert ev_masked["mask_detected"] == 1

        all_events = store.list_events(None, 10)
        assert len(all_events) == 2

        masked_only = store.list_events(None, 10, mask_detected=True)
        assert len(masked_only) == 1
        assert masked_only[0]["id"] == ev_masked["id"]

        unmasked_only = store.list_events(None, 10, mask_detected=False)
        assert len(unmasked_only) == 1
        assert unmasked_only[0]["id"] == ev_unmasked["id"]


def test_api_masked_event_endpoints() -> None:
    with TestClient(create_app()) as client:
        token = client.post(
            "/v1/auth/login",
            json={
                "username": "owner",
                "password": "changeme",
                "device_name": "test_phone",
                "device_role": "phone",
            },
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        store = client.app.state.store
        with store.cursor() as cur:
            cur.execute("DELETE FROM events")

        store.add_event("person", 0.88, None, camera="door", mask_detected=True)
        store.add_event("person", 0.82, None, camera="door", mask_detected=False)

        # 1. Filtered list
        res_masked = client.get("/v1/events?masked=true", headers=headers)
        assert res_masked.status_code == 200
        events_m = res_masked.json()["events"]
        assert len(events_m) == 1
        assert events_m[0]["mask_detected"] is True
        assert events_m[0]["mask_status"] == "masked"

        # 2. Search endpoint
        res_search = client.get("/v1/events/search?q=masked person at the door", headers=headers)
        assert res_search.status_code == 200
        search_events = res_search.json()["events"]
        assert len(search_events) == 1
        assert search_events[0]["mask_detected"] is True
