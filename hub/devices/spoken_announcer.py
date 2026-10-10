"""Spoken announcements via Piper TTS and ONVIF RTSP backchannel to Doorbell Speaker."""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from typing import Optional

import numpy as np

from hub import config
from hub.devices.talkback import TalkbackSession

logger = logging.getLogger("home_ai.announcer")

_PIPER_VOICE = None
_VOICE_LOCK = threading.Lock()


def get_piper_voice():
    """Load and cache PiperVoice instance."""
    global _PIPER_VOICE
    with _VOICE_LOCK:
        if _PIPER_VOICE is not None:
            return _PIPER_VOICE

        model_path = config.PIPER_MODEL_PATH
        config_path = config.PIPER_CONFIG_PATH

        if not (os.path.exists(model_path) and os.path.exists(config_path)):
            logger.info("Piper voice model not found at %s. Announcer disabled.", model_path)
            return None

        try:
            import piper

            _PIPER_VOICE = piper.PiperVoice.load(model_path, config_path=config_path)
            logger.info("Piper voice loaded for doorbell announcements.")
            return _PIPER_VOICE
        except Exception as exc:
            logger.error("Failed to load Piper voice: %s", exc)
            return None


def resample_to_8k(samples: np.ndarray, orig_rate: int) -> np.ndarray:
    """Resample audio numpy array to 8000 Hz using linear interpolation."""
    if orig_rate == 8000:
        return samples.astype(np.int16)
    duration = len(samples) / orig_rate
    target_len = int(round(duration * 8000))
    orig_times = np.linspace(0, duration, len(samples), endpoint=False)
    target_times = np.linspace(0, duration, target_len, endpoint=False)
    return np.interp(target_times, orig_times, samples).astype(np.int16)


def synthesize_pcm8k(text: str) -> Optional[np.ndarray]:
    """Synthesize text into 8 kHz mono int16 PCM."""
    voice = get_piper_voice()
    if voice is None:
        return None

    try:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_out:
            voice.synthesize_wav(text, wav_out)

        buf.seek(0)
        with wave.open(buf, "rb") as wav_in:
            rate = wav_in.getframerate()
            frames = wav_in.readframes(wav_in.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16)
            pcm_8k = resample_to_8k(samples, rate)
            return pcm_8k
    except Exception as exc:
        logger.error("Synthesis error: %s", exc)
        return None


def speak_to_doorbell(text: str, camera_url: Optional[str] = None) -> bool:
    """Synthesize speech and transmit to Reolink doorbell speaker over ONVIF backchannel."""
    url = camera_url or config.CAMERA_URL
    if not url or not config.TALKBACK_ENABLED:
        logger.info("Doorbell talkback disabled or no camera URL.")
        return False

    pcm = synthesize_pcm8k(text)
    if pcm is None or len(pcm) == 0:
        logger.warning("No audio synthesized for: %s", text)
        return False

    # Pad audio with leading and trailing silence:
    # 1. Leading silence (0.6s) primes the Reolink backchannel jitter buffer and
    #    allows the speaker amplifier circuit to unmute before the first spoken word,
    #    preventing "Security alert:" or the opening greeting from being clipped.
    # 2. Trailing silence (1.2s) ensures all speech samples play out through the
    #    doorbell speaker hardware buffer before RTSP TEARDOWN shuts down the channel,
    #    preventing the final words (e.g. "immediately") from being truncated.
    leading_silence = np.zeros(int(8000 * 0.6), dtype=np.int16)
    trailing_silence = np.zeros(int(8000 * 1.2), dtype=np.int16)
    padded_pcm = np.concatenate([leading_silence, pcm, trailing_silence])

    logger.info(
        "Speaking to doorbell speaker: '%s' (%d samples, padded %d)",
        text,
        len(pcm),
        len(padded_pcm),
    )
    session = TalkbackSession(url)
    if not session.start():
        logger.warning("Failed to start talkback session for doorbell.")
        return False

    try:
        # Feed in chunks of 1024 samples (128ms)
        chunk_size = 1024
        for i in range(0, len(padded_pcm), chunk_size):
            chunk = padded_pcm[i : i + chunk_size]
            session.write_pcm8k(chunk)
            time.sleep(0.12)  # Pace sending close to real time

        if hasattr(session, "flush"):
            session.flush()

        # Wait for remaining audio to play out of the speaker buffer
        time.sleep(1.0)
        return True
    finally:
        session.close()


def announce_async(text: str, camera_url: Optional[str] = None) -> threading.Thread:
    """Run speech announcement to doorbell speaker in background thread."""
    thread = threading.Thread(
        target=speak_to_doorbell,
        args=(text, camera_url),
        name="doorbell-announcer",
        daemon=True,
    )
    thread.start()
    return thread
