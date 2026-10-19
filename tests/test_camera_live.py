"""Live JPEG camera sockets used by the iPhone preview."""

from __future__ import annotations

import os

os.environ["HUB_VISION_ENABLED"] = "0"
os.environ["HUB_AUDIO_ENABLED"] = "0"
os.environ["HUB_DOORBELL_ENABLED"] = "0"
os.environ["HUB_TALKBACK_ENABLED"] = "0"
os.environ["HUB_CAMERA_URL"] = ""
os.environ["HUB_DRIVEWAY_CAMERA"] = ""
os.environ["HUB_MONITOR"] = "0"
os.environ["HUB_PC_CAMERA"] = "0"
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_live_data")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hub.app import create_app


def _login(client: TestClient) -> str:
    res = client.post(
        "/v1/auth/login",
        json={
            "username": "owner",
            "password": "changeme",
            "device_name": "iphone",
            "device_role": "phone",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_door_live_rejects_a_missing_token() -> None:
    with TestClient(create_app()) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/system/live") as socket:
                socket.receive_bytes()


def test_door_live_sends_jpeg_frames() -> None:
    with TestClient(create_app()) as client:
        token = _login(client)
        picture = np.zeros((48, 64, 3), dtype=np.uint8)
        picture[:, :, 1] = 180
        client.app.state.vision.latest_bgr = lambda: picture
        with client.websocket_connect(f"/v1/system/live?access_token={token}") as socket:
            frame = socket.receive_bytes()
        assert frame[:2] == b"\xff\xd8"
        assert frame[-2:] == b"\xff\xd9"


def test_driveway_live_sends_jpeg_frames() -> None:
    with TestClient(create_app()) as client:
        token = _login(client)
        picture = np.full((40, 40, 3), 40, dtype=np.uint8)

        class _Camera:
            def latest_bgr(self):
                return picture

        client.app.state.driveway = _Camera()
        with client.websocket_connect(f"/v1/driveway/live?access_token={token}") as socket:
            frame = socket.receive_bytes()
        assert frame[:2] == b"\xff\xd8"
