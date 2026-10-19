"""Push live camera JPEGs to a phone over one WebSocket.

React Native on iPhone cannot play the multipart MJPEG stream the Android
driveway view reads, and Expo Go cannot open the door WebRTC call. A socket of
JPEG frames is the stream both cameras can show.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import cv2
import numpy as np
from fastapi import WebSocket

from hub.auth import decode_access_token

_MAX_WIDTH = 640
_JPEG_QUALITY = 60


async def accept_camera_socket(ws: WebSocket) -> bool:
    token = ws.query_params.get("access_token")
    if not token:
        header = ws.headers.get("authorization")
        if header and header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1].strip()
    if not token:
        await ws.close(code=4401)
        return False
    try:
        decode_access_token(ws.app.state.store, token)
    except Exception:
        await ws.close(code=4401)
        return False
    await ws.accept()
    return True


async def push_jpeg_frames(
    ws: WebSocket,
    frame_fn: Callable[[], np.ndarray | None],
    fps: float = 10.0,
) -> None:
    interval = 1.0 / max(1.0, min(fps, 12.0))
    try:
        while True:
            started = time.monotonic()
            frame = frame_fn()
            jpeg = _encode(frame) if frame is not None else None
            if jpeg:
                await ws.send_bytes(jpeg)
            remaining = interval - (time.monotonic() - started)
            await asyncio.sleep(remaining if remaining > 0 else 0)
    except Exception:
        return


def _encode(frame: np.ndarray) -> bytes | None:
    height, width = frame.shape[:2]
    if width > _MAX_WIDTH:
        scale = _MAX_WIDTH / width
        frame = cv2.resize(
            frame,
            (_MAX_WIDTH, max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
    if not ok:
        return None
    return encoded.tobytes()
