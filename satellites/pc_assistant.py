"""Dell PC Always-On Voice Satellite.

Combines:
- openWakeWord for low-power wake-word detection (<1% CPU)
- sherpa-onnx SenseVoice for Chinese and English speech-to-text
- Hub Assistant API over HTTPS with JWT authentication
- piper-tts local speech synthesis playback
"""

from __future__ import annotations

import argparse
from collections import deque
import io
import json
import logging
import os
import re
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, List, Optional, Union

import numpy as np
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pc_assistant")

POWERCONF_NAME = "powerconf"
LAPTOP_MIC_GAIN = 2.5
POWERCONF_MIC_GAIN = 1.0


class AudioDeviceError(RuntimeError):
    """The requested microphone or speaker is missing or not usable."""

DEFAULT_HUB_URL = os.getenv("HUB_URL", "https://10.0.0.83:8443")
DEFAULT_USERNAME = os.getenv("HUB_OWNER_USERNAME", "owner")
DEFAULT_PASSWORD = os.getenv("HUB_OWNER_PASSWORD", "changeme")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_WHISPER_ENCODER = str(
    ROOT_DIR / "models/sherpa-onnx-whisper-tiny.en/tiny.en-encoder.int8.onnx"
)
DEFAULT_WHISPER_DECODER = str(
    ROOT_DIR / "models/sherpa-onnx-whisper-tiny.en/tiny.en-decoder.int8.onnx"
)
DEFAULT_WHISPER_TOKENS = str(
    ROOT_DIR / "models/sherpa-onnx-whisper-tiny.en/tiny.en-tokens.txt"
)
DEFAULT_PIPER_MODEL = str(ROOT_DIR / "models/piper/en_US-lessac-medium.onnx")
DEFAULT_PIPER_CONFIG = str(ROOT_DIR / "models/piper/en_US-lessac-medium.onnx.json")
DEFAULT_SENSE_MODEL = str(
    ROOT_DIR
    / "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
)
DEFAULT_SENSE_TOKENS = str(
    ROOT_DIR / "models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
)
DEFAULT_PIPER_ZH_MODEL = str(ROOT_DIR / "models/piper/zh_CN-huayan-medium.onnx")
DEFAULT_PIPER_ZH_CONFIG = str(ROOT_DIR / "models/piper/zh_CN-huayan-medium.onnx.json")

_SENSE_TAG = re.compile(r"<\|[^|]*\|>")
_CJK_OR_PUNCT = r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
_CJK_SPACE = re.compile(rf"(?<={_CJK_OR_PUNCT})\s+(?={_CJK_OR_PUNCT})")


def contains_cjk(text: str) -> bool:
    """True when the text contains a Chinese character."""
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def clean_transcript(text: str) -> str:
    """Drop SenseVoice language tags and spaces inserted between Chinese characters."""
    cleaned = _CJK_SPACE.sub("", _SENSE_TAG.sub("", text))
    return cleaned.strip()


def find_audio_devices(
    name_substr: str = "PowerConf",
    devices: Optional[list[dict[str, Any]]] = None,
) -> tuple[Optional[int], Optional[int]]:
    """Return the first input and output indexes whose names contain name_substr."""
    if devices is None:
        import sounddevice as sd

        devices = list(sd.query_devices())
    needle = name_substr.lower()
    in_idx: Optional[int] = None
    out_idx: Optional[int] = None
    for idx, dev in enumerate(devices):
        if needle not in str(dev.get("name", "")).lower():
            continue
        if int(dev.get("max_input_channels", 0)) > 0 and in_idx is None:
            in_idx = idx
        if int(dev.get("max_output_channels", 0)) > 0 and out_idx is None:
            out_idx = idx
    return in_idx, out_idx


def resolve_audio_devices(
    spec: Optional[Union[str, int]],
    devices: Optional[list[dict[str, Any]]] = None,
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """Resolve a device index or name to input index, output index, and matched name.

    None keeps the system default for both directions.
    """
    if spec is None or spec == "":
        return None, None, None
    if devices is None:
        import sounddevice as sd

        devices = list(sd.query_devices())
    if isinstance(spec, int) or (isinstance(spec, str) and spec.strip().lstrip("-").isdigit()):
        idx = int(spec)
        if idx < 0 or idx >= len(devices):
            raise AudioDeviceError(f"Audio device index {idx} is not available")
        chosen = devices[idx]
        name = str(chosen.get("name", ""))
        in_idx = idx if int(chosen.get("max_input_channels", 0)) > 0 else None
        out_idx = None
        for other_idx, dev in enumerate(devices):
            if str(dev.get("name", "")) == name and int(dev.get("max_output_channels", 0)) > 0:
                out_idx = other_idx
                break
        if in_idx is None:
            raise AudioDeviceError(f"Audio device {idx} ({name}) has no microphone")
        return in_idx, out_idx, name

    in_idx, out_idx = find_audio_devices(str(spec), devices)
    if in_idx is None and out_idx is None:
        raise AudioDeviceError(f"No audio device matching {spec!r}. Is the PowerConf plugged in?")
    if in_idx is None:
        raise AudioDeviceError(f"Audio device matching {spec!r} has no microphone")
    matched = str(devices[in_idx].get("name", spec))
    return in_idx, out_idx, matched


def default_mic_gain(device_name: Optional[str], explicit_gain: Optional[float]) -> float:
    """Use the speakerphone's own gain unless the caller set one."""
    if explicit_gain is not None:
        return explicit_gain
    if device_name and POWERCONF_NAME in device_name.lower():
        return POWERCONF_MIC_GAIN
    return LAPTOP_MIC_GAIN


class PcmResampler:
    """Stream PCM from one sample rate to another without dropping the boundary sample."""

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = src_rate
        self.dst_rate = dst_rate
        self._pending = np.zeros(0, dtype=np.float32)
        self._phase = 0.0

    def push(self, samples: np.ndarray) -> np.ndarray:
        if len(samples) == 0:
            return np.zeros(0, dtype=np.int16)
        if self.src_rate == self.dst_rate:
            return np.asarray(samples, dtype=np.int16)
        incoming = samples.astype(np.float32)
        buf = np.concatenate([self._pending, incoming]) if len(self._pending) else incoming
        if len(buf) < 2:
            self._pending = buf
            return np.zeros(0, dtype=np.int16)
        step = self.src_rate / self.dst_rate
        pos = self._phase
        last = len(buf) - 1
        out: list[float] = []
        while pos < last:
            index = int(pos)
            frac = pos - index
            out.append(float(buf[index] * (1.0 - frac) + buf[index + 1] * frac))
            pos += step
        keep = int(pos)
        self._pending = buf[keep:]
        self._phase = pos - keep
        if not out:
            return np.zeros(0, dtype=np.int16)
        return np.asarray(out, dtype=np.int16)


def resample_pcm(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample one complete buffer. Used for playback, which is not streamed."""
    return PcmResampler(src_rate, dst_rate).push(samples)


def device_sample_rate(device: Optional[int], fallback: int = 16000) -> int:
    """Return the rate the hardware accepts. None keeps the pipeline rate."""
    if device is None:
        return fallback
    import sounddevice as sd

    info = sd.query_devices(device)
    rate = int(info.get("default_samplerate") or fallback)
    return rate or fallback


def play_pcm(samples: np.ndarray, samplerate: int, device: Optional[int] = None) -> None:
    """Play PCM on one output device, converting to that device's native rate."""
    import sounddevice as sd

    out_rate = samplerate
    if device is not None:
        out_rate = device_sample_rate(device, fallback=samplerate)
        if out_rate != samplerate:
            samples = resample_pcm(samples, samplerate, out_rate)
    kwargs: dict[str, Any] = {"samplerate": out_rate}
    if device is not None:
        kwargs["device"] = device
    sd.play(samples, **kwargs)
    sd.wait()


class HubClient:
    """HTTP client communicating with Home AI Security Hub."""

    def __init__(
        self,
        base_url: str = DEFAULT_HUB_URL,
        username: str = DEFAULT_USERNAME,
        password: str = DEFAULT_PASSWORD,
        device_name: str = "dell-pc-voice-satellite",
        device_role: str = "station",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.device_name = device_name
        self.device_role = device_role
        self.access_token: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = False  # Hub uses local self-signed TLS cert

    def login(self) -> bool:
        try:
            url = f"{self.base_url}/v1/auth/login"
            payload = {
                "username": self.username,
                "password": self.password,
                "device_name": self.device_name,
                "device_role": self.device_role,
            }
            res = self.session.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                self.access_token = data.get("access_token")
                logger.info("Authenticated with Hub at %s", self.base_url)
                return True
            logger.error("Hub login failed: HTTP %s - %s", res.status_code, res.text)
            return False
        except Exception as exc:
            logger.error("Hub connection error during login: %s", exc)
            return False

    def ask(self, prompt: str) -> dict[str, Any]:
        if not self.access_token:
            if not self.login():
                return {"response": "Could not connect to security hub."}

        url = f"{self.base_url}/v1/assistant/chat"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            res = self.session.post(url, json={"prompt": prompt}, headers=headers, timeout=60)
            if res.status_code == 401:
                # Token may have expired, retry once
                if self.login():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    res = self.session.post(
                        url, json={"prompt": prompt}, headers=headers, timeout=60
                    )
            if res.status_code == 200:
                return res.json()
            logger.error("Assistant chat error: %s - %s", res.status_code, res.text)
            return {"response": f"Hub error: HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("Error communicating with assistant API: %s", exc)
            return {"response": "Error communicating with central assistant."}

    def meeting_active(self) -> dict[str, Any] | None | str:
        body = self._meeting_request("GET", "/v1/meetings/active")
        if body is None:
            return "unavailable"
        active = body.get("active")
        return active if isinstance(active, dict) else None

    def post_meeting_chunk(self, text: str) -> None:
        self._meeting_request("POST", "/v1/meetings/active/chunks", {"text": text})

    def post_note_chunk(self, text: str) -> None:
        self._meeting_request("POST", "/v1/library/active/chunks", {"text": text})

    def finish_meeting(self) -> dict[str, Any]:
        return self._meeting_request("POST", "/v1/meetings/finish")

    def _meeting_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.access_token and not self.login():
            return {}
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            res = self.session.request(method, url, json=payload, headers=headers, timeout=60)
            if res.status_code == 401 and self.login():
                headers["Authorization"] = f"Bearer {self.access_token}"
                res = self.session.request(method, url, json=payload, headers=headers, timeout=60)
            if res.status_code == 200:
                data = res.json()
                return data if isinstance(data, dict) else {}
            logger.error("Meeting API %s %s failed: %s", method, path, res.status_code)
        except Exception as exc:
            logger.error("Meeting API error: %s", exc)
        return None


class VoiceSatellite:
    """Always-on voice satellite running wake-word detection, STT, and TTS."""

    def __init__(
        self,
        hub_client: Optional[HubClient] = None,
        wakeword: Union[str, list[str]] = "hey_jarvis",
        wake_threshold: float = 0.25,
        gain: float = LAPTOP_MIC_GAIN,
        device: Optional[int] = None,
        output_device: Optional[int] = None,
        debug: bool = False,
        whisper_encoder: str = DEFAULT_WHISPER_ENCODER,
        whisper_decoder: str = DEFAULT_WHISPER_DECODER,
        whisper_tokens: str = DEFAULT_WHISPER_TOKENS,
        sense_model: str = DEFAULT_SENSE_MODEL,
        sense_tokens: str = DEFAULT_SENSE_TOKENS,
        piper_model: str = DEFAULT_PIPER_MODEL,
        piper_config: str = DEFAULT_PIPER_CONFIG,
        piper_zh_model: str = DEFAULT_PIPER_ZH_MODEL,
        piper_zh_config: str = DEFAULT_PIPER_ZH_CONFIG,
    ) -> None:
        self.hub = hub_client or HubClient()
        if isinstance(wakeword, str):
            self.wakewords = [w.strip() for w in wakeword.split(",") if w.strip()]
        else:
            self.wakewords = list(wakeword)
        self.wakeword = self.wakewords[0] if self.wakewords else "hey_jarvis"
        self.wake_threshold = wake_threshold
        self.gain = gain
        self.device = device
        self.output_device = output_device
        self.debug = debug
        self.whisper_encoder = whisper_encoder
        self.whisper_decoder = whisper_decoder
        self.whisper_tokens = whisper_tokens
        self.sense_model = sense_model
        self.sense_tokens = sense_tokens
        self.piper_model = piper_model
        self.piper_config = piper_config
        self.piper_zh_model = piper_zh_model
        self.piper_zh_config = piper_zh_config

        self._recognizer: Any = None
        self._piper_voice: Any = None
        self._piper_voice_zh: Any = None
        self._oww_model: Any = None
        self._running = False
        self.meeting = False
        self.noting = False
        self._meeting_parts: list[np.ndarray] = []
        self._meeting_count = 0
        self._meeting_lock = threading.Lock()
        self._stt_lock = threading.Lock()

    def init_stt(self) -> bool:
        try:
            import sherpa_onnx
        except Exception as exc:
            logger.error("Failed to import sherpa-onnx: %s", exc)
            return False

        if os.path.exists(self.sense_model) and os.path.exists(self.sense_tokens):
            try:
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=self.sense_model,
                    tokens=self.sense_tokens,
                    num_threads=4,
                    language="auto",
                    use_itn=True,
                )
                logger.info("Sherpa-ONNX SenseVoice STT loaded for Chinese and English.")
                return True
            except Exception as exc:
                logger.error("Failed to load SenseVoice STT: %s", exc)

        if not (
            os.path.exists(self.whisper_encoder)
            and os.path.exists(self.whisper_decoder)
            and os.path.exists(self.whisper_tokens)
        ):
            logger.warning("No speech recognition model files found.")
            return False

        try:
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=self.whisper_encoder,
                decoder=self.whisper_decoder,
                tokens=self.whisper_tokens,
                num_threads=2,
            )
            logger.info("Sherpa-ONNX Whisper STT loaded. Chinese speech will not be transcribed.")
            return True
        except Exception as exc:
            logger.error("Failed to load Sherpa-ONNX STT: %s", exc)
            return False

    def _load_piper(self, model: str, config: str, label: str) -> Any:
        if not (os.path.exists(model) and os.path.exists(config)):
            logger.warning("%s Piper voice not found.", label)
            return None
        try:
            import piper

            voice = piper.PiperVoice.load(model, config_path=config)
            logger.info("%s Piper voice loaded.", label)
            return voice
        except Exception as exc:
            logger.error("Failed to load %s Piper voice: %s", label, exc)
            return None

    def init_tts(self) -> bool:
        self._piper_voice = self._load_piper(self.piper_model, self.piper_config, "English")
        self._piper_voice_zh = self._load_piper(
            self.piper_zh_model, self.piper_zh_config, "Chinese"
        )
        return self._piper_voice is not None or self._piper_voice_zh is not None

    def init_wakeword(self) -> bool:
        try:
            import openwakeword
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            # Pass a copy so openwakeword in-place mutation does not affect self.wakewords
            models_to_load = list(self.wakewords)
            download_models(model_names=models_to_load)
            self._oww_model = Model(
                wakeword_models=models_to_load,
                inference_framework="onnx",
            )
            loaded_keys = list(self._oww_model.models.keys())
            logger.info("openWakeWord loaded active wake models: %s", loaded_keys)
            return True
        except Exception as exc:
            logger.error("Failed to load openWakeWord: %s", exc)
            return False

    def transcribe_audio(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe float32 audio numpy array with sherpa-onnx."""
        if self._recognizer is None:
            self.init_stt()
        if self._recognizer is None:
            return ""

        with self._stt_lock:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(sample_rate, audio_data)
            self._recognizer.decode_stream(stream)
            return clean_transcript(stream.result.text)

    def speak(self, text: str) -> None:
        """Speak text through PC speakers."""
        if not text:
            return

        logger.info("Speaking: %s", text)
        if self._piper_voice is None and self._piper_voice_zh is None:
            self.init_tts()

        voice = self._piper_voice
        if contains_cjk(text) and self._piper_voice_zh is not None:
            voice = self._piper_voice_zh
        elif contains_cjk(text):
            logger.warning("Chinese voice is not loaded. Speaking with the English voice.")

        if voice is not None:
            try:
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wav_out:
                    voice.synthesize_wav(text, wav_out)
                buf.seek(0)
                with wave.open(buf, "rb") as wav_in:
                    samplerate = wav_in.getframerate()
                    frames = wav_in.readframes(wav_in.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16)
                    play_pcm(samples, samplerate, self.output_device)
                return
            except Exception as exc:
                logger.warning("Piper TTS playback error (%s). Falling back.", exc)

        # Fallback to Windows SAPI on Windows
        if sys.platform == "win32":
            try:
                import subprocess

                clean_text = text.replace("'", " ")
                cmd = f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('{clean_text}')"
                subprocess.run(["powershell", "-Command", cmd], check=False)
            except Exception as exc:
                logger.error("SAPI playback error: %s", exc)

    def play_chime(self) -> None:
        """Play a short tone on the selected speaker."""
        try:
            sample_rate = 16000
            t = np.linspace(0, 0.12, int(sample_rate * 0.12), False)
            tone = (np.sin(2 * np.pi * 880 * t) * 0.25 * 32767).astype(np.int16)
            play_pcm(tone, sample_rate, self.output_device)
        except Exception as exc:
            logger.warning("Wake chime playback failed: %s", exc)

    def process_voice_turn(
        self, audio_chunk: np.ndarray, command_pcm: Optional[np.ndarray] = None
    ) -> None:
        """Process a spoken query: transcribe, ask Hub, and speak answer."""
        if (self.meeting or self.noting) and command_pcm is not None and command_pcm.size:
            self._append_meeting_audio(command_pcm)
            self._flush_meeting_chunk(force=True, wait=True)
        logger.info("Transcribing speech...")
        transcript = self.transcribe_audio(audio_chunk)
        if not transcript:
            logger.info("No speech detected.")
            return

        logger.info("Transcribed: %s", transcript)
        res = self.hub.ask(transcript)
        tool = res.get("tool_used")
        if tool == "start_meeting":
            self.meeting = True
            self._clear_meeting_audio()
        elif tool == "end_meeting":
            self.meeting = False
            self._clear_meeting_audio()
        elif tool == "start_note" and not self.meeting:
            self.noting = True
            self._clear_meeting_audio()
        elif tool == "end_note":
            self.noting = False
            self._clear_meeting_audio()
        spoken_response = res.get("response", "")
        if spoken_response:
            self.speak(spoken_response)

    def _watch_meeting(self) -> None:
        while self._running:
            self.sync_meeting()
            time.sleep(2)

    def sync_meeting(self) -> None:
        """Follow a meeting started or stopped from the phone."""
        try:
            active = self.hub.meeting_active()
        except Exception as exc:
            logger.warning("Meeting status check failed: %s", exc)
            return
        if active == "unavailable":
            return
        state = str(active.get("state")) if isinstance(active, dict) else ""
        if state == "recording" and not self.meeting:
            self.meeting = True
            self._clear_meeting_audio()
            logger.info("Meeting recording started from the hub.")
        elif state == "stopping" and self.meeting:
            self._flush_meeting_chunk(force=True, wait=True)
            self.hub.finish_meeting()
            self.meeting = False
            self._clear_meeting_audio()
            logger.info("Meeting recording flushed and finished.")
        elif not state and self.meeting:
            self.meeting = False
            self._clear_meeting_audio()

    def _append_meeting_audio(self, samples: np.ndarray) -> None:
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            return
        with self._meeting_lock:
            self._meeting_parts.append(audio)
            self._meeting_count += int(audio.size)

    def _clear_meeting_audio(self) -> None:
        with self._meeting_lock:
            self._meeting_parts = []
            self._meeting_count = 0

    def _flush_meeting_chunk(self, force: bool = False, wait: bool = False) -> None:
        need = 16000 * 45
        with self._meeting_lock:
            if self._meeting_count == 0:
                return
            if not force and self._meeting_count < need:
                return
            audio = np.concatenate(self._meeting_parts)
            self._meeting_parts = []
            self._meeting_count = 0
        if wait:
            self._post_meeting_audio(audio)
        else:
            threading.Thread(target=self._post_meeting_audio, args=(audio,), daemon=True).start()

    def _post_meeting_audio(self, audio: np.ndarray) -> None:
        text = self.transcribe_audio(audio)
        if text:
            logger.info("Meeting chunk: %s", text)
            if self.noting and not self.meeting:
                self.hub.post_note_chunk(text)
            else:
                self.hub.post_meeting_chunk(text)

    def run_listening_loop(self) -> None:
        """Always-on microphone capture loop."""
        import sounddevice as sd

        if not self.init_wakeword():
            logger.error("Cannot start listening without openWakeWord.")
            raise RuntimeError("openWakeWord failed to load")
        self.init_stt()
        self.init_tts()

        sample_rate = 16000
        frame_size = 1280  # 80ms at 16kHz, the size openWakeWord consumes
        capture_rate = device_sample_rate(self.device, fallback=sample_rate)
        capture_chunk = max(1, int(capture_rate * frame_size / sample_rate))
        resampler = PcmResampler(capture_rate, sample_rate)
        self._running = True
        threading.Thread(target=self._watch_meeting, daemon=True).start()

        logger.info(
            "Listening for wake-word(s) %s (threshold: %.2f, gain: %.1fx, capture %d Hz)...",
            self.wakewords,
            self.wake_threshold,
            self.gain,
            capture_rate,
        )

        # Rolling circular buffer for the last ~1.6 seconds of audio
        pre_roll: deque[np.ndarray] = deque(maxlen=20)
        pending = np.zeros(0, dtype=np.int16)

        with sd.InputStream(
            device=self.device,
            samplerate=capture_rate,
            channels=1,
            dtype="int16",
        ) as mic:
            while self._running:
                data, _ = mic.read(capture_chunk)
                raw_samples = data.flatten()

                # Apply gain boost, then convert to the 16 kHz wake-word rate.
                boosted = raw_samples.astype(np.float32) * self.gain
                captured = np.clip(boosted, -32768, 32767).astype(np.int16)
                pending = np.concatenate([pending, resampler.push(captured)])
                if len(pending) < frame_size:
                    continue
                samples = pending[:frame_size]
                pending = pending[frame_size:]
                pre_roll.append(samples)
                if self.meeting or self.noting:
                    self._append_meeting_audio(samples.astype(np.float32) / 32768.0)
                    self._flush_meeting_chunk()

                # Feed wake-word model
                prediction = self._oww_model.predict(samples)
                best_model = None
                best_score = 0.0

                if prediction:
                    best_model = max(prediction, key=prediction.get)
                    best_score = float(prediction[best_model])

                if self.debug:
                    peak = int(np.max(np.abs(samples)))
                    print(
                        f"\r[Mic peak: {peak:5d} | {best_model}: {best_score:.3f}]   ",
                        end="",
                        flush=True,
                    )

                if best_score >= self.wake_threshold:
                    if self.debug:
                        print()
                    logger.info("Wake-word '%s' detected! (score: %.3f)", best_model, best_score)
                    self._oww_model.reset()
                    threading.Thread(target=self.play_chime, daemon=True).start()

                    # Record next 3.5 seconds of user speech
                    logger.info("Listening for command...")
                    query_chunks = [pending]
                    pending = np.zeros(0, dtype=np.int16)
                    query_samples = int(sample_rate * 3.5)
                    samples_read = len(query_chunks[0])
                    while samples_read < query_samples and self._running:
                        chunk, _ = mic.read(capture_chunk)
                        c_boosted = chunk.flatten().astype(np.float32) * self.gain
                        c_samples = np.clip(c_boosted, -32768, 32767).astype(np.int16)
                        speech = resampler.push(c_samples)
                        if len(speech) == 0:
                            continue
                        query_chunks.append(speech)
                        samples_read += len(speech)

                    # Combine pre-roll (includes query if spoken right away) and new chunks
                    full_audio = np.concatenate(list(pre_roll) + query_chunks)
                    float_audio = full_audio.astype(np.float32) / 32768.0

                    command_pcm = None
                    if (self.meeting or self.noting) and query_chunks:
                        command_pcm = np.concatenate(query_chunks).astype(np.float32) / 32768.0
                    self.process_voice_turn(float_audio, command_pcm)
                    pre_roll.clear()
                    logger.info("Resuming wake-word listening...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dell PC Voice Assistant Satellite")
    parser.add_argument(
        "--hub-url", default=DEFAULT_HUB_URL, help="Hub HTTPS base URL"
    )
    parser.add_argument("--query", help="Run a single text query without mic")
    parser.add_argument(
        "--listen", action="store_true", help="Start always-on listening mode"
    )
    parser.add_argument(
        "--wakeword", default="hey_jarvis,alexa", help="Comma-separated wake-word models (e.g. hey_jarvis,alexa)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.25, help="Wake-word score threshold (default: 0.25)"
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=None,
        help="Software mic gain. Defaults to 1.0 for PowerConf and 2.5 otherwise.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Audio device index or name substring, for example PowerConf",
    )
    parser.add_argument(
        "--list-devices", action="store_true", help="List audio input devices and exit"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Show real-time audio levels and wake-word scores"
    )
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd

        print("Available audio devices:")
        for idx, dev in enumerate(sd.query_devices()):
            inn = int(dev.get("max_input_channels", 0))
            out = int(dev.get("max_output_channels", 0))
            if inn or out:
                print(
                    f"  [{idx}] {dev['name']} (in: {inn}, out: {out}, default sr: {int(dev['default_samplerate'])})"
                )
        return

    try:
        input_device, output_device, device_name = resolve_audio_devices(args.device)
    except AudioDeviceError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    gain = default_mic_gain(device_name, args.gain)
    if device_name:
        logger.info(
            "Audio device %s: input %s, output %s, gain %.1f",
            device_name,
            input_device,
            output_device,
            gain,
        )

    client = HubClient(base_url=args.hub_url)
    satellite = VoiceSatellite(
        hub_client=client,
        wakeword=args.wakeword,
        wake_threshold=args.threshold,
        gain=gain,
        device=input_device,
        output_device=output_device,
        debug=args.debug,
    )

    if args.query:
        logger.info("Sending query: %s", args.query)
        res = client.ask(args.query)
        print("Response:", res.get("response"))
        satellite.speak(res.get("response", ""))
    elif args.listen:
        try:
            satellite.run_listening_loop()
        except RuntimeError as exc:
            logger.error("%s", exc)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
