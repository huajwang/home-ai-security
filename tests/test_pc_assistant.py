"""Tests for Dell PC voice satellite client."""

from __future__ import annotations

import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from satellites.pc_assistant import (
    AudioDeviceError,
    HubClient,
    PcmResampler,
    VoiceSatellite,
    clean_transcript,
    default_mic_gain,
    find_audio_devices,
    play_pcm,
    resolve_audio_devices,
)


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


def test_start_meeting_begins_recording_and_end_meeting_flushes():
    hub_mock = MagicMock()
    hub_mock.ask.side_effect = [
        {"response": "The meeting has started.", "tool_used": "start_meeting"},
        {"response": "The minutes are ready.", "tool_used": "end_meeting"},
    ]
    satellite = VoiceSatellite(hub_client=hub_mock)
    satellite.transcribe_audio = MagicMock(return_value="start the meeting")
    satellite.speak = MagicMock()
    satellite._flush_meeting_chunk = MagicMock()

    audio = np.zeros(1600, dtype=np.float32)
    satellite.process_voice_turn(audio)
    assert satellite.meeting is True
    satellite._flush_meeting_chunk.assert_not_called()

    satellite.transcribe_audio.return_value = "end the meeting"
    command = np.ones(1600, dtype=np.float32)
    satellite.process_voice_turn(audio, command)
    satellite._flush_meeting_chunk.assert_called_once_with(force=True, wait=True)
    assert satellite.meeting is False


def test_start_note_begins_dictation_and_end_note_flushes():
    hub_mock = MagicMock()
    hub_mock.ask.side_effect = [
        {"response": "The note has started.", "tool_used": "start_note"},
        {"response": "The note is saved.", "tool_used": "end_note"},
    ]
    satellite = VoiceSatellite(hub_client=hub_mock)
    satellite.transcribe_audio = MagicMock(return_value="start a note")
    satellite.speak = MagicMock()
    satellite._flush_meeting_chunk = MagicMock()
    audio = np.zeros(1600, dtype=np.float32)
    satellite.process_voice_turn(audio)
    assert satellite.noting is True
    satellite.transcribe_audio.return_value = "end the note"
    satellite.process_voice_turn(audio, np.ones(1600, dtype=np.float32))
    satellite._flush_meeting_chunk.assert_called_once_with(force=True, wait=True)
    assert satellite.noting is False


_DEVICES = [
    {"name": "rockchip-hdmi0", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Anker PowerConf", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "Anker PowerConf", "max_input_channels": 0, "max_output_channels": 2},
]


def test_find_audio_devices_matches_powerconf_input_and_output():
    mic, speaker = find_audio_devices("PowerConf", _DEVICES)
    assert mic == 1
    assert speaker == 2


def test_resolve_name_is_case_insensitive():
    mic, speaker, name = resolve_audio_devices("powerconf", _DEVICES)
    assert (mic, speaker, name) == (1, 2, "Anker PowerConf")


def test_resolve_missing_name_raises():
    with pytest.raises(AudioDeviceError, match="plugged in"):
        resolve_audio_devices(
            "PowerConf",
            [{"name": "HDMI", "max_input_channels": 0, "max_output_channels": 2}],
        )


def test_resolve_missing_index_raises():
    with pytest.raises(AudioDeviceError, match="not available"):
        resolve_audio_devices(9, _DEVICES)


def test_powerconf_uses_hardware_gain_unless_overridden():
    assert default_mic_gain("Anker PowerConf", None) == 1.0
    assert default_mic_gain("Anker PowerConf", 2.5) == 2.5
    assert default_mic_gain("Laptop Mic", None) == 2.5


def _wav_voice() -> MagicMock:
    voice = MagicMock()

    def synthesize(text: str, wav_out: wave.Wave_write) -> None:
        del text
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(16000)
        wav_out.writeframes(b"\x00\x01" * 8)

    voice.synthesize_wav.side_effect = synthesize
    return voice


def test_speak_and_chime_use_the_output_device():
    satellite = VoiceSatellite(hub_client=MagicMock(), output_device=2)
    satellite._piper_voice = _wav_voice()
    with patch("satellites.pc_assistant.play_pcm") as play:
        satellite.speak("The front door is locked.")
        satellite.play_chime()
    assert play.call_count == 2
    assert all(call.args[2] == 2 for call in play.call_args_list)


def test_resampler_converts_48k_chunks_to_16k_frames():
    resampler = PcmResampler(48000, 16000)
    first = resampler.push(np.zeros(3840, dtype=np.int16))
    second = resampler.push(np.zeros(3840, dtype=np.int16))
    assert len(first) == 1280
    assert len(second) == 1280


def test_play_pcm_uses_the_device_native_rate():
    fake = MagicMock()
    fake.query_devices.return_value = {"default_samplerate": 48000.0}
    samples = np.zeros(1600, dtype=np.int16)
    with patch.dict("sys.modules", {"sounddevice": fake}):
        play_pcm(samples, 16000, device=6)
    played = fake.play.call_args
    assert played.kwargs["device"] == 6
    assert played.kwargs["samplerate"] == 48000
    assert abs(len(played.args[0]) - 4800) <= 4


def test_clean_transcript_keeps_chinese_and_drops_tags():
    raw = "<|zh|><|NEUTRAL|><|Speech|> 系 统 已 布 防 。"
    assert clean_transcript(raw) == "系统已布防。"


def test_speak_uses_the_chinese_voice_for_chinese_text():
    satellite = VoiceSatellite(hub_client=MagicMock(), output_device=2)
    english = _wav_voice()
    chinese = _wav_voice()
    satellite._piper_voice = english
    satellite._piper_voice_zh = chinese
    with patch("satellites.pc_assistant.play_pcm"):
        satellite.speak("系统已布防。")
        satellite.speak("The system is armed.")
    chinese.synthesize_wav.assert_called_once()
    english.synthesize_wav.assert_called_once()


def test_speak_reports_a_busy_output_device(caplog):
    satellite = VoiceSatellite(hub_client=MagicMock(), output_device=2)
    satellite._piper_voice = _wav_voice()
    with patch("satellites.pc_assistant.play_pcm", side_effect=RuntimeError("device busy")):
        satellite.speak("hello")
    assert "device busy" in caplog.text
