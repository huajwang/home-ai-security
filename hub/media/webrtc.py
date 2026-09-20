"""WebRTC door peer: annotated camera frames, PC mic, PC speakers."""

from __future__ import annotations

import asyncio
import fractions
import queue
import threading
import time
import uuid
from typing import Any

import numpy as np
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.sdp import candidate_from_sdp
from av import AudioFrame, VideoFrame
from av.audio.resampler import AudioResampler

from hub import config
from hub.api.deps import event_payload
from hub.devices.talkback import DoorTalkback, from_config as talkback_from_config
from hub.media.clips import ClipRecorder
from hub.vision.worker import VisionWorker

try:
    import sounddevice as sd
except Exception:  # noqa: BLE001
    sd = None


class AnnotatedVideoTrack(VideoStreamTrack):
    """Downscaled camera frames using aiortc's 90 kHz timestamps so VP8 encodes."""

    kind = "video"

    def __init__(self, vision: VisionWorker) -> None:
        super().__init__()
        self.vision = vision

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        frame = self.vision.latest_webrtc_bgr()
        if frame is None:
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
        av_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        av_frame.pts = pts
        av_frame.time_base = time_base
        return av_frame


def _try_microphone() -> Any | None:
    if not config.AUDIO_ENABLED or sd is None:
        return None
    try:
        from aiortc import AudioStreamTrack

        class _Mic(AudioStreamTrack):
            def __init__(self) -> None:
                super().__init__()
                self.samplerate = config.AUDIO_SAMPLE_RATE
                self.samples = 960
                self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=8)
                self._stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=1,
                    dtype="int16",
                    blocksize=self.samples,
                    callback=self._callback,
                )
                self._stream.start()
                self._timestamp = 0

            def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
                try:
                    self._queue.put_nowait(indata.copy())
                except asyncio.QueueFull:
                    pass

            async def recv(self) -> AudioFrame:
                try:
                    data = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except TimeoutError:
                    data = np.zeros((self.samples, 1), dtype=np.int16)
                samples = data.reshape(-1)
                frame = AudioFrame.from_ndarray(np.array([samples]), format="s16", layout="mono")
                frame.sample_rate = self.samplerate
                frame.pts = self._timestamp
                frame.time_base = fractions.Fraction(1, self.samplerate)
                self._timestamp += samples.shape[0]
                return frame

            def stop(self) -> None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                super().stop()

        return _Mic()
    except Exception as exc:  # noqa: BLE001
        print(f"Microphone unavailable: {exc}")
        return None


def _to_s16_mono(samples: np.ndarray) -> np.ndarray:
    pcm = np.asarray(samples).reshape(-1)
    if np.issubdtype(pcm.dtype, np.floating):
        return np.clip(pcm * 32767.0, -32768, 32767).astype(np.int16)
    if pcm.dtype != np.int16:
        return pcm.astype(np.int16)
    return pcm


async def _play_remote_audio(track: Any, session: CallSession) -> None:
    """Decode tablet audio and play it on the doorbell speaker (PC speakers as fallback)."""
    talk = talkback_from_config()
    if talk is not None:
        started = await asyncio.to_thread(talk.start)
        if started:
            session.talkback = talk
            print(f"Call {session.id} playing audio on doorbell speaker")
            try:
                await _feed_talkback(track, talk)
            finally:
                talk.close()
                session.talkback = None
            return
        talk.close()
        print(f"Call {session.id} doorbell talkback unavailable; using PC speakers")
    await _play_pc_speakers(track)


async def _feed_talkback(track: Any, talk: DoorTalkback) -> None:
    resampler = AudioResampler(format="s16", layout="mono", rate=8000)
    first = True
    try:
        while True:
            frame = await track.recv()
            for converted in resampler.resample(frame):
                pcm = _to_s16_mono(converted.to_ndarray())
                if first:
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0
                    print(f"Doorbell talkback PCM samples={pcm.size} rms={rms:.1f}")
                    first = False
                talk.write_pcm8k(pcm)
    except Exception as exc:  # noqa: BLE001
        print(f"Remote audio ended: {exc}")


async def _play_pc_speakers(track: Any) -> None:
    if sd is None or not config.AUDIO_ENABLED:
        print("Remote audio skipped: sounddevice/audio disabled")
        return
    try:
        out_info = sd.query_devices(kind="output")
        print(f"Playing tablet audio on: {out_info.get('name')}")
    except Exception as exc:  # noqa: BLE001
        print(f"Speaker query failed: {exc}")
    resampler = AudioResampler(format="s16", layout="mono", rate=config.AUDIO_SAMPLE_RATE)
    pending: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=40)
    stop = threading.Event()

    def _speaker() -> None:
        try:
            stream = sd.OutputStream(
                samplerate=config.AUDIO_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=960,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001
            print(f"Speakers unavailable: {exc}")
            return
        try:
            while not stop.is_set():
                try:
                    pcm = pending.get(timeout=0.25)
                except queue.Empty:
                    continue
                if pcm is None:
                    break
                stream.write(pcm.reshape(-1, 1))
        except Exception as exc:  # noqa: BLE001
            print(f"Speaker write failed: {exc}")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    worker = threading.Thread(target=_speaker, name="door-speaker", daemon=True)
    worker.start()
    first = True
    try:
        while True:
            frame = await track.recv()
            if first:
                print(
                    f"Remote audio frame rate={getattr(frame, 'sample_rate', None)} "
                    f"fmt={getattr(frame, 'format', None)} layout={getattr(frame, 'layout', None)}"
                )
            for converted in resampler.resample(frame):
                pcm = _to_s16_mono(converted.to_ndarray())
                if first:
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0
                    print(f"Remote audio first PCM samples={pcm.size} rms={rms:.1f}")
                    first = False
                try:
                    pending.put_nowait(pcm)
                except queue.Full:
                    try:
                        pending.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        pending.put_nowait(pcm)
                    except queue.Full:
                        pass
    except Exception as exc:  # noqa: BLE001
        print(f"Remote audio ended: {exc}")
    finally:
        stop.set()
        try:
            pending.put_nowait(None)
        except queue.Full:
            pass


class CallSession:
    def __init__(self, call_id: str, pc: RTCPeerConnection, user_id: int) -> None:
        self.id = call_id
        self.pc = pc
        self.user_id = user_id
        self.created_at = time.time()
        self.pending_ice: list[dict[str, Any]] = []
        self.tasks: list[asyncio.Task] = []
        self.remote_ready = False
        self.mic = None
        self.audio_playing = False
        self.talkback = None


class CallManager:
    def __init__(self, vision: VisionWorker) -> None:
        self.vision = vision
        self._calls: dict[str, CallSession] = {}
        self.clips = ClipRecorder(vision)

    def create(self, user_id: int) -> CallSession:
        call_id = str(uuid.uuid4())
        # Empty list, not None: aiortc treats None as stun.l.google.com (5s STUN wait).
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        session = CallSession(call_id, pc, user_id)
        pc.addTrack(AnnotatedVideoTrack(self.vision))
        mic = _try_microphone()
        session.mic = mic
        if mic is not None:
            pc.addTrack(mic)

        def _start_remote_audio(track: Any) -> None:
            if session.audio_playing or track is None or getattr(track, "kind", None) != "audio":
                return
            session.audio_playing = True
            print(f"Call {call_id} starting tablet playback")
            session.tasks.append(asyncio.create_task(_play_remote_audio(track, session)))

        @pc.on("track")
        def on_track(track: Any) -> None:
            print(f"Call {call_id} remote track {track.kind}")
            _start_remote_audio(track)

        @pc.on("iceconnectionstatechange")
        async def on_ice_state() -> None:
            state = pc.iceConnectionState
            print(f"Call {call_id} ICE {state}")
            if state in {"connected", "completed"}:
                for receiver in pc.getReceivers():
                    _start_remote_audio(getattr(receiver, "track", None))
            # "disconnected" is often a brief consent-check blip (~15-20s). Do not tear down.
            if state in {"failed", "closed"}:
                await self.hangup(call_id)

        self._calls[call_id] = session
        return session

    def get(self, call_id: str) -> CallSession | None:
        return self._calls.get(call_id)

    async def handle_offer(self, call_id: str, sdp: str, sdp_type: str = "offer") -> dict[str, str]:
        session = self._calls.get(call_id)
        if session is None:
            raise KeyError(call_id)
        started = time.monotonic()
        await session.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))
        session.remote_ready = True
        await self._flush_ice(session)
        answer = await session.pc.createAnswer()
        await session.pc.setLocalDescription(answer)
        local = session.pc.localDescription
        print(f"Call {call_id} answer in {time.monotonic() - started:.2f}s")
        return {"sdp": local.sdp, "type": local.type}

    async def handle_answer(self, call_id: str, sdp: str, sdp_type: str = "answer") -> None:
        session = self._calls.get(call_id)
        if session is None:
            raise KeyError(call_id)
        await session.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))
        session.remote_ready = True
        await self._flush_ice(session)

    async def add_ice(self, call_id: str, candidate: dict[str, Any]) -> None:
        session = self._calls.get(call_id)
        if session is None:
            raise KeyError(call_id)
        session.pending_ice.append(candidate)
        if session.remote_ready:
            await self._flush_ice(session)

    async def _flush_ice(self, session: CallSession) -> None:
        pending = session.pending_ice
        session.pending_ice = []
        for candidate in pending:
            raw = (candidate.get("candidate") or "").strip()
            if not raw:
                continue
            if raw.startswith("candidate:"):
                raw = raw.split(":", 1)[1]
            ice = candidate_from_sdp(raw)
            ice.sdpMid = candidate.get("sdpMid")
            ice.sdpMLineIndex = candidate.get("sdpMLineIndex")
            await session.pc.addIceCandidate(ice)

    def save_photo(self) -> dict[str, Any]:
        frame = self.vision.latest_bgr()
        if frame is None:
            raise LookupError("no_frame")
        path = self.vision.save_snapshot(frame)
        event = self.vision.store.add_event("photo", 1.0, path)
        print(f"Photo event {event['id']}")
        self.vision._publish({"type": "photo_saved", "event": event_payload(event)})
        return event

    def start_clip(self) -> None:
        self.clips.start()
        print("Clip recording started")

    def stop_clip(self) -> dict[str, Any]:
        clip, thumb = self.clips.stop()
        event = self.vision.store.add_event("clip", 1.0, thumb, clip)
        print(f"Clip event {event['id']}")
        self.vision._publish({"type": "clip_saved", "event": event_payload(event)})
        return event

    async def hangup(self, call_id: str) -> None:
        session = self._calls.pop(call_id, None)
        if session is None:
            return
        if self.clips.recording() and not self._calls:
            try:
                self.stop_clip()
            except Exception:
                pass
        for task in session.tasks:
            task.cancel()
        if session.mic is not None:
            try:
                session.mic.stop()
            except Exception:
                pass
        if session.talkback is not None:
            try:
                session.talkback.close()
            except Exception:
                pass
            session.talkback = None
        await session.pc.close()

