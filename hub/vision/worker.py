"""Doorway capture + YOLO. Live Talk frames are not gated on inference."""

from __future__ import annotations

import asyncio
import os
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
from hub.vision.people import shared_detector
from hub.vision.visits import ObjectVisits


def _safe_source(source: str | int) -> str:
    text = str(source)
    if "://" in text and "@" in text:
        scheme, rest = text.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}"
    return text


def _open_camera(source: str | int):
    if isinstance(source, str) and source.lower().startswith("rtsp"):
        try:
            from hub.vision.decode import MppCapture

            camera = MppCapture(source)
            if camera.isOpened():
                print(f"Hardware decoder opened {_safe_source(source)}")
                return camera
            camera.release()
        except Exception as exc:  # noqa: BLE001
            print(f"Hardware decoder idle: {exc}")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0"
        )
        software = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        software.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print(f"Software decoder opened {_safe_source(source)}")
        return software
    return cv2.VideoCapture(source)


def _rtc_frame(frame: np.ndarray) -> np.ndarray:
    width = frame.shape[1]
    if width > config.WEBRTC_MAX_WIDTH:
        scale = config.WEBRTC_MAX_WIDTH / width
        return cv2.resize(
            frame,
            (config.WEBRTC_MAX_WIDTH, max(1, int(frame.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    return frame.copy()


class VisionWorker:
    def __init__(self, store: Store, state: HubState, bus: EventBus) -> None:
        self.store = store
        self.state = state
        self.bus = bus
        self.lights = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._detect_thread: threading.Thread | None = None
        self._frame_lock = threading.Lock()
        self._latest_raw: np.ndarray | None = None
        self._latest_bgr: np.ndarray | None = None
        self._latest_rtc: np.ndarray | None = None
        self._frame_id = 0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        if not config.VISION_ENABLED:
            self.state.vision_error = "Vision disabled (HUB_VISION_ENABLED=0)"
            return
        self._stop.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, name="vision-capture", daemon=True)
        self._detect_thread = threading.Thread(target=self._detect_loop, name="vision-detect", daemon=True)
        self._capture_thread.start()
        self._detect_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in (self._capture_thread, self._detect_thread):
            if thread is not None:
                thread.join(timeout=4)

    def latest_bgr(self) -> np.ndarray | None:
        """Annotated frame when detection is running, otherwise the live capture."""
        with self._frame_lock:
            frame = self._latest_bgr if self._latest_bgr is not None else self._latest_raw
            if frame is None:
                return None
            return frame.copy()

    def latest_webrtc_bgr(self) -> np.ndarray | None:
        """Smaller copy for software VP8 encode. Safe to hold without the lock."""
        with self._frame_lock:
            if self._latest_rtc is None:
                return None
            return self._latest_rtc.copy()

    def _publish(self, payload: dict) -> None:
        if self.loop is not None:
            self.bus.publish_threadsafe(self.loop, payload)

    def _deter_light(self, turn_on: bool) -> threading.Thread | None:
        """Turn paired bulbs on or off without stalling the camera loop."""
        lights = self.lights
        if lights is None:
            return None

        ieee = config.DOOR_LIGHT or None

        def run() -> None:
            try:
                lights.set_on(turn_on, ieee)
            except Exception as exc:  # noqa: BLE001
                state = "on" if turn_on else "off"
                print(f"Door light {state} failed: {exc}")

        thread = threading.Thread(target=run, name="door-light", daemon=True)
        thread.start()
        return thread

    def save_snapshot(self, image: np.ndarray) -> str:
        filename = f"event_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = Path(config.SNAPSHOT_DIR) / filename
        cv2.imwrite(str(path), image)
        return str(path)

    def _save_snapshot(self, image: np.ndarray) -> str:
        return self.save_snapshot(image)

    def _publish_live(self, frame: np.ndarray) -> None:
        rtc = _rtc_frame(frame)
        raw = frame.copy()
        with self._frame_lock:
            self._latest_raw = raw
            self._latest_rtc = rtc
            self._frame_id += 1

    def _newest_raw(self, last_id: int) -> tuple[int, np.ndarray | None]:
        with self._frame_lock:
            if self._latest_raw is None or self._frame_id == last_id:
                return last_id, None
            return self._frame_id, self._latest_raw.copy()

    def _capture_loop(self) -> None:
        config.ensure_dirs()
        source: str | int = config.CAMERA_URL or config.CAMERA_INDEX
        camera = None
        fail_streak = 0
        fps_t0 = time.time()
        fps_n = 0

        while not self._stop.is_set():
            if camera is None or not camera.isOpened():
                if camera is not None:
                    camera.release()
                camera = _open_camera(source)
                if not camera.isOpened():
                    camera.release()
                    camera = None
                    self.state.vision_running = False
                    self.state.vision_error = f"Could not open camera {_safe_source(source)}"
                    print(f"ERROR: {self.state.vision_error}")
                    time.sleep(2.0)
                    continue
                print(f"Vision opened camera {_safe_source(source)}")
                self.state.vision_running = True
                self.state.vision_error = None
                fail_streak = 0
                fps_t0 = time.time()
                fps_n = 0

            success, frame = camera.read()
            if not success or frame is None:
                fail_streak += 1
                self.state.vision_error = "Could not read a camera frame"
                if fail_streak >= 20:
                    print(f"Vision reconnecting {_safe_source(source)}")
                    camera.release()
                    camera = None
                    fail_streak = 0
                    time.sleep(0.4)
                else:
                    time.sleep(0.05)
                continue
            fail_streak = 0
            if self.state.vision_error == "Could not read a camera frame":
                self.state.vision_error = None
            self._publish_live(frame)
            fps_n += 1
            elapsed = time.time() - fps_t0
            if elapsed >= 1.0:
                self.state.vision_fps = fps_n / elapsed
                fps_n = 0
                fps_t0 = time.time()

        if camera is not None:
            camera.release()
        self.state.vision_running = False
        print("Vision capture stopped.")

    def _detect_loop(self) -> None:
        try:
            detector = shared_detector()
        except Exception as exc:  # noqa: BLE001
            self.state.vision_error = f"Could not load person detection: {exc}"
            print(f"ERROR: {self.state.vision_error}")
            return

        print(f"Vision watching for: {sorted(config.ALLOWED_LABELS)}")
        other_visits = ObjectVisits()
        person_streak = 0
        last_alarm_time = 0.0
        visit_notified = False
        lingering_since: float | None = None
        deterrent_spoken = False
        target_confirmed = False
        last_seen_person = 0.0
        last_id = -1
        roi_x1, roi_y1, roi_x2, roi_y2 = config.ROI

        while not self._stop.is_set():
            last_id, frame = self._newest_raw(last_id)
            if frame is None:
                time.sleep(0.01)
                continue

            detections = detector.detect(frame)
            display = frame.copy()
            target_count = 0
            best_conf = 0.0
            seen_other: dict[str, float] = {}

            if config.USE_ROI:
                cv2.rectangle(display, (roi_x1, roi_y1), (roi_x2, roi_y2), (255, 255, 0), 2)

            for label, confidence, x1, y1, x2, y2 in detections:
                if config.USE_ROI:
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    if not (roi_x1 <= cx <= roi_x2 and roi_y1 <= cy <= roi_y2):
                        continue
                if label in config.ALLOWED_LABELS:
                    target_count += 1
                    best_conf = max(best_conf, confidence)
                elif label in config.RECORD_LABELS:
                    seen_other[label] = max(seen_other.get(label, 0.0), confidence)
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

            now = time.time()
            if target_count > 0:
                person_streak += 1
                last_seen_person = now
                self.state.mark_person(best_conf)
                if person_streak >= config.FRAMES_REQUIRED_FOR_ALERT:
                    target_confirmed = True
            else:
                person_streak = 0

            # Stay confirmed across brief frame drops (up to 2.5s) so slight motion/lighting doesn't flap state
            person_present = target_confirmed and (now - last_seen_person < 2.5)
            snap = self.state.snapshot()

            if person_present and not visit_notified:
                if now - last_alarm_time >= config.ALARM_COOLDOWN_SECONDS:
                    visit_notified = True
                    last_alarm_time = now
                    if snap["armed"]:
                        self.state.set_alarm(True)
                        self._deter_light(True)
                    snapshot_path = self._save_snapshot(display)
                    event = self.store.add_event(
                        next(iter(config.ALLOWED_LABELS), "person"),
                        best_conf,
                        snapshot_path,
                        camera="door",
                    )
                    print(f"Person event {event['id']} confidence={best_conf:.2f}")
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

            if person_present and snap["armed"]:
                if lingering_since is None:
                    lingering_since = now
                elif now - lingering_since >= 5.0 and not deterrent_spoken:
                    deterrent_spoken = True
                    if config.DOORBELL_DETERRENT:
                        from hub.devices.spoken_announcer import announce_async

                        announce_async(config.DETERRENT_WARNING)
                        print("Lingering armed person -> Spoke deterrent warning.")

            if not person_present:
                target_confirmed = False
                visit_notified = False
                lingering_since = None
                deterrent_spoken = False
                if snap["alarm_active"] and self.state.set_alarm(False):
                    print("Target gone → alarm cleared")
                    self._publish({"type": "alarm_cleared"})
                    self._deter_light(False)

            for label, confidence in other_visits.update(seen_other, now):
                path = self._save_snapshot(display)
                event = self.store.add_event(label, confidence, path, camera="door")
                print(f"Door {label} event {event['id']} confidence={confidence:.2f}")

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
            with self._frame_lock:
                self._latest_bgr = display

            if config.VISION_DEBUG_WINDOW:
                cv2.imshow("Home Hub vision (debug)", display)
                if cv2.waitKey(1) & 0xFF in {ord("q"), ord("Q")}:
                    break

        if config.VISION_DEBUG_WINDOW:
            cv2.destroyAllWindows()
        print("Vision detect stopped.")
