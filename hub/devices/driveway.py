"""Second camera for the driveway. The doorbell keeps HUB_CAMERA_URL."""

from __future__ import annotations

import threading
import time
from typing import Any

import cv2
import numpy as np

from hub import config
from hub.notify import EventBus
from hub.storage import Store
from hub.vision.worker import _open_camera, _safe_source


def _encode_jpeg(frame: np.ndarray) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        return None
    return encoded.tobytes()


def camera_source(value: str) -> str | int:
    text = value.strip()
    if text.startswith("/"):
        return text
    return int(text)


class DrivewayCamera:
    def __init__(self, store: Store, bus: EventBus) -> None:
        self.store = store
        self.bus = bus
        self.loop = None
        self._stop = threading.Event()
        self._capture: threading.Thread | None = None
        self._detect: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id = 0
        self._error: str | None = None
        self._fps = 0.0
        self._running = False

    def start(self, loop: Any) -> None:
        self.loop = loop
        if not config.DRIVEWAY_CAMERA:
            return
        self._stop.clear()
        self._capture = threading.Thread(target=self._capture_loop, name="driveway-capture", daemon=True)
        self._detect = threading.Thread(target=self._detect_loop, name="driveway-detect", daemon=True)
        self._capture.start()
        self._detect.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in (self._capture, self._detect):
            if thread is not None:
                thread.join(timeout=6)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(config.DRIVEWAY_CAMERA),
            "name": "driveway",
            "ready": self._running and self._frame is not None,
            "running": self._running,
            "fps": round(self._fps, 1),
            "error": self._error,
        }

    def jpeg(self) -> bytes | None:
        frame = self._copy_frame()
        if frame is None:
            return None
        return _encode_jpeg(frame)

    def mjpeg(self):
        """Multipart JPEG stream. Stops when the viewer disconnects."""
        last_id = -1
        while not self._stop.is_set():
            with self._lock:
                frame_id = self._frame_id
                frame = None if self._frame is None or frame_id == last_id else self._frame.copy()
            if frame is None:
                time.sleep(0.03)
                continue
            last_id = frame_id
            payload = _encode_jpeg(frame)
            if payload is None:
                continue
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n"
            )
            yield header + payload + b"\r\n"

    def _copy_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def _publish(self, payload: dict) -> None:
        if self.loop is not None:
            self.bus.publish_threadsafe(self.loop, payload)

    def _capture_loop(self) -> None:
        source = camera_source(config.DRIVEWAY_CAMERA)
        camera = _open_camera(source)
        if not camera.isOpened():
            self._error = f"Could not open driveway camera {_safe_source(source)}"
            print(f"ERROR: {self._error}")
            return
        print(f"Driveway camera opened {_safe_source(source)}")
        self._running = True
        self._error = None
        fail_streak = 0
        fps_t0 = time.time()
        fps_n = 0
        while not self._stop.is_set():
            success, frame = camera.read()
            if not success or frame is None:
                fail_streak += 1
                if fail_streak >= 3:
                    print(f"Driveway camera reconnecting {_safe_source(source)}")
                    camera.release()
                    time.sleep(0.4)
                    camera = _open_camera(source)
                    fail_streak = 0
                    if not camera.isOpened():
                        self._error = f"Could not reopen driveway camera {_safe_source(source)}"
                        time.sleep(1.0)
                else:
                    time.sleep(0.05)
                continue
            fail_streak = 0
            self._error = None
            with self._lock:
                self._frame = frame
                self._frame_id += 1
            fps_n += 1
            elapsed = time.time() - fps_t0
            if elapsed >= 1.0:
                self._fps = fps_n / elapsed
                fps_n = 0
                fps_t0 = time.time()
        camera.release()
        self._running = False
        print("Driveway camera stopped.")

    def _detect_loop(self) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            print(f"Driveway detection idle: {exc}")
            return
        try:
            model = YOLO(config.YOLO_MODEL)
        except Exception as exc:  # noqa: BLE001
            print(f"Driveway detection idle: {exc}")
            return
        print("Driveway watching for a person")
        streak = 0
        last_alarm = 0.0
        visit_notified = False
        last_id = -1
        while not self._stop.is_set():
            with self._lock:
                if self._frame is None or self._frame_id == last_id:
                    frame = None
                else:
                    last_id = self._frame_id
                    frame = self._frame.copy()
            if frame is None:
                time.sleep(0.05)
                continue
            results = model(frame, verbose=False)
            result = results[0]
            names = result.names
            boxes = result.boxes
            count = 0
            best = 0.0
            display = frame.copy()
            if boxes is not None:
                for box in boxes:
                    label = names[int(box.cls[0])]
                    confidence = float(box.conf[0])
                    if label not in config.ALLOWED_LABELS or confidence < config.CONFIDENCE_THRESHOLD:
                        continue
                    count += 1
                    best = max(best, confidence)
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                    cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
            with self._lock:
                self._frame = display
            if count > 0:
                streak += 1
            else:
                streak = 0
                visit_notified = False
            now = time.time()
            if streak >= config.FRAMES_REQUIRED_FOR_ALERT and not visit_notified:
                if now - last_alarm >= config.ALARM_COOLDOWN_SECONDS:
                    visit_notified = True
                    last_alarm = now
                    path = self._save(display)
                    event = self.store.add_event("driveway", best, path)
                    print(f"Driveway person event {event['id']} confidence={best:.2f}")
                    self._publish(
                        {
                            "type": "person_at_driveway",
                            "event": {
                                "id": event["id"],
                                "ts": event["ts"],
                                "label": event["label"],
                                "confidence": event["confidence"],
                                "snapshot_url": f"/v1/events/{event['id']}/snapshot",
                            },
                        }
                    )
            time.sleep(0.05)

    def _save(self, image: np.ndarray) -> str:
        from datetime import datetime
        from pathlib import Path

        config.ensure_dirs()
        filename = f"driveway_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = Path(config.SNAPSHOT_DIR) / filename
        cv2.imwrite(str(path), image)
        return str(path)
