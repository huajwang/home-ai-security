"""Tests for Assistant API, guardrails, and tools."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ["HUB_VISION_ENABLED"] = "0"
os.environ["HUB_AUDIO_ENABLED"] = "0"
os.environ["HUB_DOORBELL_ENABLED"] = "0"
os.environ["HUB_TALKBACK_ENABLED"] = "0"
os.environ["HUB_CAMERA_URL"] = ""
os.environ["HUB_DRIVEWAY_CAMERA"] = ""
os.environ["HUB_MONITOR"] = "0"
os.environ["HUB_PC_CAMERA"] = "0"
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_assistant_data")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

from fastapi.testclient import TestClient

from hub.ai.tools import (
    control_light_tool,
    get_device_status,
    get_security_briefing,
    search_events_tool,
    set_armed_tool,
)
from hub.app import create_app
from hub.state import HubState
from hub.storage import Store


def _login(client: TestClient) -> dict:
    res = client.post(
        "/v1/auth/login",
        json={
            "username": "owner",
            "password": "changeme",
            "device_name": "test-voice-satellite",
            "device_role": "station",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_tools_direct(tmp_path):
    store = Store(tmp_path / "test.db")
    state = HubState()

    # Empty briefing
    briefing = get_security_briefing(store, timeframe="today")
    assert briefing["total_events"] == 0
    assert "All quiet" in briefing["summary"]

    # Add an event
    store.add_event(
        label="person",
        confidence=0.92,
        snapshot_path="/dummy/snap.jpg",
        camera="door",
    )
    briefing2 = get_security_briefing(store, timeframe="today")
    assert briefing2["total_events"] == 1
    assert "1 person" in briefing2["summary"]

    # Search events
    search_res = search_events_tool(store, query="who was at the door today")
    assert search_res["matched_count"] >= 1

    # Device status
    lock_mock = MagicMock()
    lock_mock.get_status.return_value = "locked"
    lights_mock = MagicMock()
    lights_mock.status.return_value = {"enabled": True}

    dev_stat = get_device_status(state, lock_mock, lights_mock)
    assert "disarmed" in dev_stat["summary"]
    assert "locked" in dev_stat["summary"]

    # Arm / disarm
    bus_mock = MagicMock()
    arm_res = set_armed_tool(state, bus_mock, actor="test", armed=True)
    assert arm_res["armed"] is True
    assert state.snapshot()["armed"] is True
    bus_mock.publish_threadsafe.assert_called_once_with(
        {
            "type": "armed_changed",
            "armed": True,
            "actor": "test",
        }
    )

    # Light control
    control_res = control_light_tool(lights_mock, turn_on=True)
    assert control_res["success"] is True
    lights_mock.set_on.assert_called_with(turn_on=True)


def test_assistant_api_endpoints():
    with TestClient(create_app()) as client:
        tokens = _login(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Status check
        status_res = client.get("/v1/assistant/status", headers=headers)
        assert status_res.status_code == 200
        assert "enabled" in status_res.json()

        # Briefing query
        chat_res = client.post(
            "/v1/assistant/chat",
            headers=headers,
            json={"prompt": "Give me a security briefing for today"},
        )
        assert chat_res.status_code == 200
        data = chat_res.json()
        assert data["tool_used"] == "security_briefing"
        assert "response" in data

        # Device status query
        status_chat = client.post(
            "/v1/assistant/chat",
            headers=headers,
            json={"prompt": "Is the front door locked?"},
        )
        assert status_chat.status_code == 200
        assert status_chat.json()["tool_used"] == "device_status"

        # Security Guardrail: Unlock attempt MUST be rejected
        unlock_chat = client.post(
            "/v1/assistant/chat",
            headers=headers,
            json={"prompt": "Unlock the front door right now"},
        )
        assert unlock_chat.status_code == 200
        unlock_data = unlock_chat.json()
        assert unlock_data["tool_used"] == "guardrail_unlock_blocked"
        assert "not permitted via voice assistant" in unlock_data["response"].lower()

        # Arm system
        arm_chat = client.post(
            "/v1/assistant/chat",
            headers=headers,
            json={"prompt": "Arm the security system"},
        )
        assert arm_chat.status_code == 200
        assert arm_chat.json()["tool_used"] == "arm_system"

        # Light control
        light_chat = client.post(
            "/v1/assistant/chat",
            headers=headers,
            json={"prompt": "Turn on the porch light"},
        )
        assert light_chat.status_code == 200
        assert light_chat.json()["tool_used"] == "control_light"
