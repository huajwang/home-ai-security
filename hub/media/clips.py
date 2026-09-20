"""Save a Talk-session video clip from live doorway frames."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

import cv2

from hub import config
from hub.vision.worker import VisionWorker


class ClipRecorder:
    def __init__(self, vision: VisionWorker) -> None:
        self.vision = vision
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._clip_path: str | None = None
        self._thumb_path: str | None = None
        self._error: str | None = None

    def recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.recording():
                raise RuntimeError("already_recording")
            frame = self.vision.latest_bgr()
            if frame is None:
                raise LookupError("no_frame")
            config.ensure_dirs()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            clip_path = Path(config.CLIP_DIR) / f"clip_{stamp}.mp4"
            thumb_path = self.vision.save_snapshot(frame)
            height, width = frame.shape[:2]
            fps = max(5.0, min(float(config.WEBRTC_FPS), 20.0))
            writer = cv2.VideoWriter(
                str(clip_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                writer.release()
                raise RuntimeError("Could not start clip writer")
            self._stop.clear()
            self._clip_path = str(clip_path)
            self._thumb_path = thumb_path
            self._error = None
            self._thread = threading.Thread(
                target=self._run,
                args=(writer, fps, (width, height)),
                name="clip-recorder",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> tuple[str, str]:
        with self._lock:
            thread = self._thread
            clip = self._clip_path
            thumb = self._thumb_path
        self._stop.set()
        if thread is not None:
            thread.join(timeout=6)
        with self._lock:
            self._thread = None
            err = self._error
            self._clip_path = None
            self._thumb_path = None
        if err:
            raise RuntimeError(err)
        if not clip or not thumb:
            raise LookupError("no_clip")
        return clip, thumb

    def _run(self, writer: cv2.VideoWriter, fps: float, size: tuple[int, int]) -> None:
        started = time.time()
        delay = 1.0 / fps
        try:
            while not self._stop.is_set():
                if time.time() - started >= config.CLIP_MAX_SECONDS:
                    break
                frame = self.vision.latest_bgr()
                if frame is not None:
                    if (frame.shape[1], frame.shape[0]) != size:
                        frame = cv2.resize(frame, size)
                    writer.write(frame)
                time.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
        finally:
            writer.release()
