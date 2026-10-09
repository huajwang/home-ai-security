"""Tests for Dell PC voice satellite client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from satellites.pc_assistant import HubClient, VoiceSatellite


def test_hub_client_login_and_ask():
    client = HubClient(base_url="https://mock-hub:8443")
    mock_resp_login = MagicMock()
    mock_resp_login.status_code = 200
    mock_resp_login.json.return_value = {"access_token": "mock-token-xyz"}

    mock_resp_chat = MagicMock()
    mock_resp_chat.status_code = 200
    mock_resp_chat.json.return_value = {
        "response": "Front door is locked.",
        "tool_used": "device_status",
    }

    with patch.object(client.session, "post") as mock_post:
        mock_post.side_effect = [mock_resp_login, mock_resp_chat]

        res = client.ask("Is the door locked?")
        assert res["response"] == "Front door is locked."
        assert client.access_token == "mock-token-xyz"
        assert mock_post.call_count == 2


def test_voice_satellite_process_turn():
    hub_mock = MagicMock()
    hub_mock.ask.return_value = {"response": "System is armed."}

    satellite = VoiceSatellite(hub_client=hub_mock)
    satellite.transcribe_audio = MagicMock(return_value="Check security status")
    satellite.speak = MagicMock()

    dummy_audio = np.zeros(16000, dtype=np.float32)
    satellite.process_voice_turn(dummy_audio)

    satellite.transcribe_audio.assert_called_once_with(dummy_audio)
    hub_mock.ask.assert_called_once_with("Check security status")
    satellite.speak.assert_called_once_with("System is armed.")
