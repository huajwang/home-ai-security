"""Unit tests for doorbell spoken announcer, receptionist, and spoken deterrent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from hub.devices.spoken_announcer import (
    announce_async,
    resample_to_8k,
    speak_to_doorbell,
    synthesize_pcm8k,
)


def test_resample_to_8k():
    orig_rate = 16000
    samples = np.sin(np.linspace(0, 10, orig_rate)).astype(np.int16)
    resampled = resample_to_8k(samples, orig_rate)
    assert len(resampled) == 8000
    assert resampled.dtype == np.int16


def test_speak_to_doorbell_mocked():
    with patch("hub.devices.spoken_announcer.config") as mock_config, patch(
        "hub.devices.spoken_announcer.TalkbackSession"
    ) as mock_talkback_cls, patch(
        "hub.devices.spoken_announcer.synthesize_pcm8k"
    ) as mock_synth:
        mock_config.TALKBACK_ENABLED = True
        mock_config.CAMERA_URL = "rtsp://admin:pass@10.0.0.112:554/h264Preview_01_main"

        mock_pcm = np.zeros(2048, dtype=np.int16)
        mock_synth.return_value = mock_pcm

        mock_session = MagicMock()
        mock_session.start.return_value = True
        mock_talkback_cls.return_value = mock_session

        res = speak_to_doorbell("Security alert")
        assert res is True
        mock_session.start.assert_called_once()
        assert mock_session.write_pcm8k.call_count == 2
        mock_session.close.assert_called_once()


def test_announce_async():
    with patch("hub.devices.spoken_announcer.speak_to_doorbell") as mock_speak:
        thread = announce_async("Hello")
        thread.join(timeout=2.0)
        mock_speak.assert_called_once_with("Hello", None)
