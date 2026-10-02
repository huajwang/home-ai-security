"""Send this computer's webcam to the hub monitor.

Run on the PC, not on the ROCK:

    python -m hub.pc_camera_send 10.0.0.83
"""

from __future__ import annotations

import socket
import sys
import time

import cv2


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "10.0.0.83"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8091
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        raise SystemExit("Could not open this PC's webcam")
    print(f"Sending this PC's webcam to {host}:{port}")
    while True:
        try:
            with socket.create_connection((host, port), timeout=5) as conn:
                while True:
                    ok, frame = camera.read()
                    if not ok or frame is None:
                        time.sleep(0.2)
                        continue
                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70]
                    )
                    if not encoded_ok:
                        continue
                    payload = encoded.tobytes()
                    conn.sendall(len(payload).to_bytes(4, "big") + payload)
                    time.sleep(0.1)
        except (OSError, TimeoutError):
            time.sleep(1)


if __name__ == "__main__":
    main()
