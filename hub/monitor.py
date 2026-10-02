"""HDMI camera screen.

The hub keeps the cameras open and writes the latest frame for each one.
`python -m hub.monitor` draws those frames fullscreen on the logged-in display.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from hub import config

WINDOW = "Cameras"
_MAX_TILES = 4


def compose_wall(slots: list[tuple[str, np.ndarray | None]], width: int, height: int) -> np.ndarray:
    """Place up to four labeled cameras on one screen."""
    width = max(int(width), 1)
    height = max(int(height), 1)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    shown = slots[:_MAX_TILES] or [("No camera", None)]
    count = len(shown)
    if count <= 1:
        cols, rows = 1, 1
    elif count == 2:
        cols, rows = 2, 1
    elif count == 3:
        cols, rows = 3, 1
    else:
        cols, rows = 2, 2
    cell_w = width // cols
    cell_h = height // rows
    for index, (label, frame) in enumerate(shown):
        row, col = divmod(index, cols)
        x0 = col * cell_w
        y0 = row * cell_h
        cell = _fit(frame, cell_w, cell_h)
        _label(cell, label)
        canvas[y0 : y0 + cell_h, x0 : x0 + cell_w] = cell
    return canvas


def _fit(frame: np.ndarray | None, cell_w: int, cell_h: int) -> np.ndarray:
    cell = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
    if frame is None or frame.size == 0 or cell_w < 2 or cell_h < 2:
        return cell
    frame_h, frame_w = frame.shape[:2]
    if frame_h < 1 or frame_w < 1:
        return cell
    scale = min(cell_w / frame_w, cell_h / frame_h)
    target_w = max(1, int(frame_w * scale))
    target_h = max(1, int(frame_h * scale))
    resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
    x = (cell_w - target_w) // 2
    y = (cell_h - target_h) // 2
    cell[y : y + target_h, x : x + target_w] = resized
    return cell


def _label(cell: np.ndarray, label: str) -> None:
    height, width = cell.shape[:2]
    bar = min(48, max(24, height // 12))
    cv2.rectangle(cell, (0, height - bar), (width, height), (0, 0, 0), thickness=-1)
    cv2.putText(
        cell,
        label,
        (16, height - max(8, bar // 3)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


class _PcCamera:
    """Receive JPEG frames from a webcam on another computer."""

    def __init__(self) -> None:
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="pc-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        server = self._server
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def latest(self) -> np.ndarray | None:
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def _serve(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", config.PC_CAMERA_PORT))
        server.listen(1)
        server.settimeout(1.0)
        self._server = server
        print(f"PC camera listening on {config.PC_CAMERA_PORT}")
        while not self._stop.is_set():
            try:
                conn, _addr = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            conn.settimeout(2.0)
            try:
                self._read(conn)
            finally:
                conn.close()
        server.close()

    def _read(self, conn: socket.socket) -> None:
        pending = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            if not chunk:
                return
            pending += chunk
            while len(pending) >= 4:
                size = int.from_bytes(pending[:4], "big")
                if size <= 0 or size > 2_000_000:
                    return
                if len(pending) < 4 + size:
                    break
                payload = pending[4 : 4 + size]
                pending = pending[4 + size :]
                if not payload.startswith(b"\xff\xd8"):
                    continue
                frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                with self._lock:
                    self._frame = frame


class MonitorPublisher:
    """Write the latest camera frames where the screen process can read them."""

    def __init__(self, vision, driveway) -> None:
        self.vision = vision
        self.driveway = driveway
        self._pc = _PcCamera()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not config.MONITOR_ENABLED:
            return
        directory = config.MONITOR_DIR
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        self._write_manifest(directory)
        self._stop.clear()
        if config.PC_CAMERA_ENABLED:
            self._pc.start()
        self._thread = threading.Thread(target=self._loop, name="monitor-wall", daemon=True)
        self._thread.start()
        print(f"Monitor publishing camera frames to {directory}")

    def stop(self) -> None:
        self._stop.set()
        self._pc.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _slots(self) -> list[tuple[str, str, np.ndarray | None]]:
        slots: list[tuple[str, str, np.ndarray | None]] = []
        if config.CAMERA_URL or config.VISION_ENABLED:
            slots.append(("door", "Front door", self.vision.latest_bgr()))
        if config.DRIVEWAY_CAMERA:
            slots.append(("driveway", "Driveway", self.driveway.latest_bgr()))
        if config.PC_CAMERA_ENABLED:
            slots.append(("pc", config.PC_CAMERA_LABEL, self._pc.latest()))
        return slots

    def _write_manifest(self, directory: Path) -> None:
        payload = {
            "slots": [{"id": slot_id, "label": label} for slot_id, label, _frame in self._slots()]
        }
        _atomic_write(directory / "manifest.json", json.dumps(payload).encode("utf-8"))

    def _loop(self) -> None:
        directory = config.MONITOR_DIR
        while not self._stop.is_set():
            for slot_id, _label, frame in self._slots():
                if frame is None:
                    continue
                encoded = _encode_jpeg(frame)
                if encoded is None:
                    continue
                _atomic_write(directory / f"{slot_id}.jpg", encoded)
            self._stop.wait(0.12)


def _encode_jpeg(frame: np.ndarray) -> bytes | None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        return None
    return encoded.tobytes()


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def screen_size() -> tuple[int, int]:
    try:
        output = subprocess.check_output(["xrandr"], text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return 1920, 1200
    connected = [line for line in output.splitlines() if " connected " in line]
    ordered = [line for line in connected if " primary " in line] + connected
    for line in ordered:
        for part in line.split():
            if "x" not in part or "+" not in part or not part[0].isdigit():
                continue
            width, rest = part.split("x", 1)
            height = rest.split("+", 1)[0]
            return int(width), int(height)
    return 1920, 1200


def load_slots(directory: Path) -> list[tuple[str, np.ndarray | None]]:
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        described = manifest.get("slots") or []
    except (OSError, json.JSONDecodeError):
        described = []
    slots: list[tuple[str, np.ndarray | None]] = []
    for item in described[:_MAX_TILES]:
        slot_id = str(item.get("id") or "")
        label = str(item.get("label") or slot_id or "Camera")
        frame = cv2.imread(str(directory / f"{slot_id}.jpg"))
        slots.append((label, frame if frame is not None else None))
    if slots:
        return slots
    return [("Waiting for the hub", None)]


def _wake_display() -> None:
    for command in (
        ["xset", "s", "off"],
        ["xset", "s", "noblank"],
        ["xset", "-dpms"],
        ["xset", "dpms", "force", "on"],
    ):
        try:
            subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def _keep_screen_awake() -> subprocess.Popen | None:
    _wake_display()
    try:
        return subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=idle:sleep",
                "--who=home-ai-monitor",
                "--why=Showing cameras",
                "--mode=block",
                "sleep",
                "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None


def main() -> None:
    if not os.environ.get("DISPLAY"):
        raise SystemExit("No display. The camera screen starts after the desktop logs in.")
    inhibit = _keep_screen_awake()
    width, height = screen_size()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL | getattr(cv2, "WINDOW_GUI_NORMAL", 0))
    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.moveWindow(WINDOW, 0, 0)
    print(f"Camera screen {width}x{height} from {config.MONITOR_DIR}")
    ticks = 0
    try:
        while True:
            wall = compose_wall(load_slots(config.MONITOR_DIR), width, height)
            cv2.imshow(WINDOW, wall)
            cv2.waitKey(100)
            ticks += 1
            if ticks % 50 == 0:
                _wake_display()
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 0:
                break
    finally:
        if inhibit is not None:
            inhibit.terminate()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
