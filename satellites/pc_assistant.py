"""Dell PC Always-On Voice Satellite.

Combines:
- openWakeWord for low-power wake-word detection (<1% CPU)
- sherpa-onnx whisper-tiny for local speech-to-text (~200ms)
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
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, List, Optional, Union

import numpy as np
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pc_assistant")

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
            res = self.session.post(url, json={"prompt": prompt}, headers=headers, timeout=15)
            if res.status_code == 401:
                # Token may have expired, retry once
                if self.login():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    res = self.session.post(
                        url, json={"prompt": prompt}, headers=headers, timeout=15
                    )
            if res.status_code == 200:
                return res.json()
            logger.error("Assistant chat error: %s - %s", res.status_code, res.text)
            return {"response": f"Hub error: HTTP {res.status_code}"}
        except Exception as exc:
            logger.error("Error communicating with assistant API: %s", exc)
            return {"response": "Error communicating with central assistant."}


class VoiceSatellite:
    """Always-on voice satellite running wake-word detection, STT, and TTS."""

    def __init__(
        self,
        hub_client: Optional[HubClient] = None,
        wakeword: Union[str, list[str]] = "hey_jarvis",
        wake_threshold: float = 0.25,
        gain: float = 2.5,
        device: Optional[int] = None,
        debug: bool = False,
        whisper_encoder: str = DEFAULT_WHISPER_ENCODER,
        whisper_decoder: str = DEFAULT_WHISPER_DECODER,
        whisper_tokens: str = DEFAULT_WHISPER_TOKENS,
        piper_model: str = DEFAULT_PIPER_MODEL,
        piper_config: str = DEFAULT_PIPER_CONFIG,
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
        self.debug = debug
        self.whisper_encoder = whisper_encoder
        self.whisper_decoder = whisper_decoder
        self.whisper_tokens = whisper_tokens
        self.piper_model = piper_model
        self.piper_config = piper_config

        self._recognizer: Any = None
        self._piper_voice: Any = None
        self._oww_model: Any = None
        self._running = False

    def init_stt(self) -> bool:
        if not (
            os.path.exists(self.whisper_encoder)
            and os.path.exists(self.whisper_decoder)
            and os.path.exists(self.whisper_tokens)
        ):
            logger.warning("Whisper STT model files not found.")
            return False

        try:
            import sherpa_onnx

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=self.whisper_encoder,
                decoder=self.whisper_decoder,
                tokens=self.whisper_tokens,
                num_threads=2,
            )
            logger.info("Sherpa-ONNX Whisper STT loaded.")
            return True
        except Exception as exc:
            logger.error("Failed to load Sherpa-ONNX STT: %s", exc)
            return False

    def init_tts(self) -> bool:
        if not (os.path.exists(self.piper_model) and os.path.exists(self.piper_config)):
            logger.warning("Piper TTS model files not found.")
            return False

        try:
            import piper

            self._piper_voice = piper.PiperVoice.load(
                self.piper_model, config_path=self.piper_config
            )
            logger.info("Piper TTS loaded.")
            return True
        except Exception as exc:
            logger.error("Failed to load Piper TTS: %s", exc)
            return False

    def init_wakeword(self) -> bool:
        try:
            import openwakeword
            from openwakeword.model import Model

            self._oww_model = Model(
                wakeword_models=self.wakewords,
                inference_framework="onnx",
            )
            logger.info("openWakeWord loaded with models: %s", self.wakewords)
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

        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, audio_data)
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()

    def speak(self, text: str) -> None:
        """Speak text through PC speakers."""
        if not text:
            return

        logger.info("Speaking: %s", text)
        if self._piper_voice is None:
            self.init_tts()

        if self._piper_voice is not None:
            try:
                import sounddevice as sd

                buf = io.BytesIO()
                with wave.open(buf, "wb") as wav_out:
                    self._piper_voice.synthesize_wav(text, wav_out)
                buf.seek(0)
                with wave.open(buf, "rb") as wav_in:
                    samplerate = wav_in.getframerate()
                    frames = wav_in.readframes(wav_in.getnframes())
                    samples = np.frombuffer(frames, dtype=np.int16)
                    sd.play(samples, samplerate=samplerate)
                    sd.wait()
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

    def process_voice_turn(self, audio_chunk: np.ndarray) -> None:
        """Process a spoken query: transcribe, ask Hub, and speak answer."""
        logger.info("Transcribing speech...")
        transcript = self.transcribe_audio(audio_chunk)
        if not transcript:
            logger.info("No speech detected.")
            return

        logger.info("Transcribed: %s", transcript)
        res = self.hub.ask(transcript)
        spoken_response = res.get("response", "")
        if spoken_response:
            self.speak(spoken_response)

    def run_listening_loop(self) -> None:
        """Always-on microphone capture loop."""
        import sounddevice as sd

        if not self.init_wakeword():
            logger.error("Cannot start listening without openWakeWord.")
            return
        self.init_stt()
        self.init_tts()

        sample_rate = 16000
        chunk_size = 1280  # 80ms at 16kHz
        self._running = True

        logger.info(
            "Listening for wake-word(s) %s (threshold: %.2f, gain: %.1fx)...",
            self.wakewords,
            self.wake_threshold,
            self.gain,
        )

        def play_chime():
            try:
                # Short 880Hz chime
                t = np.linspace(0, 0.12, int(sample_rate * 0.12), False)
                tone = (np.sin(2 * np.pi * 880 * t) * 0.25 * 32767).astype(np.int16)
                sd.play(tone, samplerate=sample_rate)
            except Exception:
                pass

        # Rolling circular buffer for the last ~1.6 seconds of audio
        pre_roll: deque[np.ndarray] = deque(maxlen=20)

        with sd.InputStream(
            device=self.device,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        ) as mic:
            while self._running:
                data, _ = mic.read(chunk_size)
                raw_samples = data.flatten()

                # Apply gain boost
                boosted = (raw_samples.astype(np.float32) * self.gain)
                samples = np.clip(boosted, -32768, 32767).astype(np.int16)
                pre_roll.append(samples)

                # Feed wake-word model
                prediction = self._oww_model.predict(samples)
                best_model = None
                best_score = 0.0

                for model_key, score in prediction.items():
                    for target in self.wakewords:
                        if target in model_key and score > best_score:
                            best_score = score
                            best_model = target

                if self.debug and best_score > 0.04:
                    peak = int(np.max(np.abs(samples)))
                    print(
                        f"\r[Peak: {peak:5d} | {best_model}: {best_score:.3f}]",
                        end="",
                        flush=True,
                    )

                if best_score >= self.wake_threshold:
                    if self.debug:
                        print()
                    logger.info("Wake-word '%s' detected! (score: %.3f)", best_model, best_score)
                    self._oww_model.reset()
                    threading.Thread(target=play_chime, daemon=True).start()

                    # Record next 3.5 seconds of user speech
                    logger.info("Listening for command...")
                    query_chunks = []
                    query_samples = int(sample_rate * 3.5)
                    samples_read = 0
                    while samples_read < query_samples and self._running:
                        chunk, _ = mic.read(chunk_size)
                        c_boosted = (chunk.flatten().astype(np.float32) * self.gain)
                        c_samples = np.clip(c_boosted, -32768, 32767).astype(np.int16)
                        query_chunks.append(c_samples)
                        samples_read += len(c_samples)

                    # Combine pre-roll (includes query if spoken right away) and new chunks
                    full_audio = np.concatenate(list(pre_roll) + query_chunks)
                    float_audio = full_audio.astype(np.float32) / 32768.0

                    self.process_voice_turn(float_audio)
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
        "--gain", type=float, default=2.5, help="Software mic gain multiplier (default: 2.5)"
    )
    parser.add_argument(
        "--device", type=int, default=None, help="Input audio device index"
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

        print("Available Audio Input Devices:")
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                print(
                    f"  [{idx}] {dev['name']} (channels: {dev['max_input_channels']}, default sr: {int(dev['default_samplerate'])})"
                )
        return

    client = HubClient(base_url=args.hub_url)
    satellite = VoiceSatellite(
        hub_client=client,
        wakeword=args.wakeword,
        wake_threshold=args.threshold,
        gain=args.gain,
        device=args.device,
        debug=args.debug,
    )

    if args.query:
        logger.info("Sending query: %s", args.query)
        res = client.ask(args.query)
        print("Response:", res.get("response"))
        satellite.speak(res.get("response", ""))
    elif args.listen:
        satellite.run_listening_loop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
