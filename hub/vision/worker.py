"""Doorway YOLO loop ported from Week 5 Program 20."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from hub import config
from hub.notify import EventBus
from hub.state import HubState
from hub.storage import Store


class VisionWorker:
    def __init__(self, store: Store, state: HubState, bus: EventBus) -> None:
        self.store = store
        self.state = state
        self.bus = bus
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._latest_bgr: np.ndarray | None = None
        self._latest_rtc: np.ndarray | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        if not config.VISION_ENABLED:
            self.state.vision_error = "Vision disabled (HUB_VISION_ENABLED=0)"
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)

    def latest_bgr(self) -> np.ndarray | None:
        with self._frame_lock:
            if self._latest_bgr is None:
                return None
            return self._latest_bgr.copy()

    def latest_webrtc_bgr(self) -> np.ndarray | None:
        """Smaller copy for software VP8 encode. Safe to hold without the lock."""
        with self._frame_lock:
            if self._latest_rtc is None:
                return None
            return self._latest_rtc.copy()

    def _publish(self, payload: dict) -> None:
        if self.loop is not None:
            self.bus.publish_threadsafe(self.loop, payload)

    def _save_snapshot(self, image: np.ndarray) -> str:
        filename = f"event_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = Path(config.SNAPSHOT_DIR) / filename
        cv2.imwrite(str(path), image)
        return str(path)

    def _run(self) -> None:
        config.ensure_dirs()
        camera = cv2.VideoCapture(config.CAMERA_INDEX)
        if not camera.isOpened():
            self.state.vision_running = False
            self.state.vision_error = f"Could not open camera index {config.CAMERA_INDEX}"
            print(f"ERROR: {self.state.vision_error}")
            return

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            camera.release()
            self.state.vision_error = f"ultralytics not installed: {exc}"
            print(f"ERROR: {self.state.vision_error}")
            return

        print(f"Loading YOLO model ({config.YOLO_MODEL})...")
        try:
            model = YOLO(config.YOLO_MODEL)
        except Exception as exc:  # noqa: BLE001
            camera.release()
            self.state.vision_error = f"Could not load YOLO: {exc}"
            print(f"ERROR: {self.state.vision_error}")
            return

        self.state.vision_running = True
        self.state.vision_error = None
        person_streak = 0
        last_alarm_time = 0.0
        fps_t0 = time.time()
        fps_n = 0
        roi_x1, roi_y1, roi_x2, roi_y2 = config.ROI
        print(f"Vision watching for: {sorted(config.ALLOWED_LABELS)}")

        while not self._stop.is_set():
            success, frame = camera.read()
            if not success:
                self.state.vision_error = "Could not read a camera frame"
                time.sleep(0.2)
                continue

            results = model(frame, verbose=False)
            result = results[0]
            names = result.names
            boxes = result.boxes
            display = frame.copy()
            target_count = 0
            best_conf = 0.0

            if config.USE_ROI:
                cv2.rectangle(display, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 255, 0), 2)

            if boxes is not None:
                for box in boxes:
                    label = names[int(box.cls[0])]
                    confidence = float(box.conf[0])
                    if label not in config.ALLOWED_LABELS:
                        continue
                    if confidence < config.CONFIDENCE_THRESHOLD:
                        continue
                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                    if config.USE_ROI:
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        if not (roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2):
                            continue
                    target_count += 1
                    best_conf = max(best_conf, confidence)
                    cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(
                        display,
                        f"{label} {confidence:.2f}",
                        (x1, y1 - 10 if y1 > 20 else y1 + 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        2,
                    )

            if target_count > 0:
                person_streak += 1
                self.state.mark_person(best_conf)
            else:
                person_streak = 0

            target_confirmed = person_streak >= config.FRAMES_REQUIRED_FOR_ALERT
            now = time.time()
            snap = self.state.snapshot()

            if snap["armed"] and target_confirmed and not snap["alarm_active"]:
                if now - last_alarm_time >= config.ALARM_COOLDOWN_SECONDS:
                    last_alarm_time = now
                    self.state.set_alarm(True)
                    snapshot_path = self._save_snapshot(display)
                    event = self.store.add_event(
                        next(iter(config.ALLOWED_LABELS), "person"),
                        best_conf,
                        snapshot_path,
                    )
                    print(f"ALERT event {event['id']} confidence={best_conf:.2f}")
                    self._publish(
                        {
                            "type": "person_at_door",
                            "event": {
                                "id": event["id"],
                                "ts": event["ts"],
                                "label": event["label"],
                                "confidence": event["confidence"],
                                "snapshot_url": f"/v1/events/{event['id']}/snapshot",
                            },
                        }
                    )

            if snap["alarm_active"] and not target_confirmed:
                if self.state.set_alarm(False):
                    print("Target gone → alarm cleared")
                    self._publish({"type": "alarm_cleared"})

            snap = self.state.snapshot()
            if not snap["armed"]:
                mode_text, mode_color = "DISARMED", (160, 160, 160)
            elif snap["alarm_active"]:
                mode_text, mode_color = "ALERT", (0, 0, 255)
            else:
                mode_text, mode_color = "ALL CLEAR", (0, 200, 0)

            cv2.rectangle(display, (0, 0), (display.shape[1], 90), (0, 0, 0), -1)
            cv2.putText(display, f"HOME HUB  |  {mode_text}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.85, mode_color, 2)
            cv2.putText(
                display,
                f"Count: {target_count}  streak: {person_streak}/{config.FRAMES_REQUIRED_FOR_ALERT}",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            rtc = display
            width = display.shape[1]
            if width > config.WEBRTC_MAX_WIDTH:
                scale = config.WEBRTC_MAX_WIDTH / width
                rtc = cv2.resize(
                    display,
                    (config.WEBRTC_MAX_WIDTH, max(1, int(display.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            with self._frame_lock:
                self._latest_bgr = display
                self._latest_rtc = rtc

            fps_n += 1
            elapsed = time.time() - fps_t0
            if elapsed >= 1.0:
                self.state.vision_fps = fps_n / elapsed
                fps_n = 0
                fps_t0 = time.time()

            if config.VISION_DEBUG_WINDOW:
                cv2.imshow("Home Hub vision (debug)", display)
                if cv2.waitKey(1) & 0xFF in {ord("q"), ord("Q")}:
                    break

        camera.release()
        if config.VISION_DEBUG_WINDOW:
            cv2.destroyAllWindows()
        self.state.vision_running = False
        print("Vision worker stopped.")
