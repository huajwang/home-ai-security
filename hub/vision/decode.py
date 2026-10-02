"""Hardware H.264 decode for the doorbell. USB cameras stay on V4L2."""

from __future__ import annotations

import sys

import numpy as np

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"


def _gst():
    try:
        import gi
    except ImportError:
        if _DIST_PACKAGES not in sys.path:
            sys.path.append(_DIST_PACKAGES)
        import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    return Gst


class MppCapture:
    """Read BGR frames from an RTSP H.264 camera through the RK3588 decoder."""

    def __init__(self, url: str) -> None:
        self.Gst = _gst()
        pipeline = self.Gst.parse_launch(
            "rtspsrc name=src protocols=tcp latency=100 ! "
            "rtph264depay ! h264parse ! mppvideodec ! videoconvert ! "
            "video/x-raw,format=BGR ! "
            "appsink name=sink emit-signals=false sync=false max-buffers=1 drop=true"
        )
        source = pipeline.get_by_name("src")
        source.set_property("location", url)
        self._pipeline = pipeline
        self._sink = pipeline.get_by_name("sink")
        self._pending = None
        self._opened = pipeline.set_state(self.Gst.State.PLAYING) != self.Gst.StateChangeReturn.FAILURE
        if self._opened:
            ok, frame = self._pull(8.0)
            if ok and frame is not None:
                self._pending = frame
            else:
                self.release()

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._pending is not None:
            frame = self._pending
            self._pending = None
            return True, frame
        return self._pull(0.5)

    def _pull(self, timeout_seconds: float) -> tuple[bool, np.ndarray | None]:
        sample = self._sink.emit("try-pull-sample", int(timeout_seconds * 1_000_000_000))
        if sample is None:
            return False, None
        caps = sample.get_caps().get_structure(0)
        width = caps.get_value("width")
        height = caps.get_value("height")
        buffer = sample.get_buffer()
        ok, mapping = buffer.map(self.Gst.MapFlags.READ)
        if not ok:
            return False, None
        try:
            frame = np.frombuffer(mapping.data, dtype=np.uint8)
            if frame.size < width * height * 3:
                return False, None
            return True, frame[: width * height * 3].reshape(height, width, 3).copy()
        finally:
            buffer.unmap(mapping)

    def release(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(self.Gst.State.NULL)
            self._opened = False
