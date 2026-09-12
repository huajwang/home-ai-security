"""API smoke tests (vision disabled). Run: HUB_VISION_ENABLED=0 python -m pytest tests -q"""

from __future__ import annotations

import os

os.environ["HUB_VISION_ENABLED"] = "0"
os.environ["HUB_AUDIO_ENABLED"] = "0"
os.environ["HUB_DATA_DIR"] = os.path.join(os.path.dirname(__file__), "_tmp_data")
os.environ["HUB_OWNER_USERNAME"] = "owner"
os.environ["HUB_OWNER_PASSWORD"] = "changeme"

from fastapi.testclient import TestClient

from hub.app import create_app


def _login(client: TestClient, role: str = "phone") -> dict:
    res = client.post(
        "/v1/auth/login",
        json={
            "username": "owner",
            "password": "changeme",
            "device_name": f"test-{role}",
            "device_role": role,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_unauthenticated_system() -> None:
    with TestClient(create_app()) as client:
        res = client.get("/v1/system")
        assert res.status_code == 401
        assert res.json()["code"] == "unauthorized"


def test_login_arm_lock_audit() -> None:
    with TestClient(create_app()) as client:
        tokens = _login(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        sys = client.get("/v1/system", headers=headers)
        assert sys.status_code == 200
        assert sys.json()["armed"] is False
        assert sys.json()["lock"]["adapter"] == "stub"

        armed = client.post("/v1/system/arm", headers=headers)
        assert armed.status_code == 200
        assert armed.json()["armed"] is True

        unlock = client.post("/v1/lock/unlock", headers=headers, json={"confirm": True})
        assert unlock.status_code == 200
        assert unlock.json()["state"] == "unlocked"

        again = client.post("/v1/lock/unlock", headers=headers, json={"confirm": True})
        assert again.status_code == 409

        locked = client.post("/v1/lock/lock", headers=headers)
        assert locked.status_code == 200
        assert locked.json()["state"] == "locked"

        audit = client.get("/v1/lock/audit", headers=headers)
        assert audit.status_code == 200
        assert len(audit.json()["audit"]) >= 2


def test_create_and_hangup_call() -> None:
    with TestClient(create_app()) as client:
        tokens = _login(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        created = client.post("/v1/calls", headers=headers)
        assert created.status_code == 200
        call_id = created.json()["call_id"]
        hung = client.delete(f"/v1/calls/{call_id}", headers=headers)
        assert hung.status_code == 200


def test_unlock_requires_confirm() -> None:
    with TestClient(create_app()) as client:
        tokens = _login(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        res = client.post("/v1/lock/unlock", headers=headers, json={"confirm": False})
        assert res.status_code == 400
