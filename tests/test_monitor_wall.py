"""The HDMI wall places the cameras that are actually publishing."""

from __future__ import annotations

import numpy as np

from hub.monitor import compose_wall


def test_two_cameras_share_one_screen() -> None:
    door = np.full((20, 40, 3), 10, dtype=np.uint8)
    driveway = np.full((30, 30, 3), 200, dtype=np.uint8)
    wall = compose_wall([("Front door", door), ("Driveway", driveway)], 200, 100)
    assert wall.shape == (100, 200, 3)
    # Each half keeps its own picture instead of stretching one camera across both.
    assert wall[40, 40, 0] == 10
    assert wall[40, 150, 0] == 200


def test_three_cameras_sit_in_one_row() -> None:
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    wall = compose_wall([("Front door", frame), ("Driveway", frame), ("This PC", frame)], 300, 90)
    assert wall.shape == (90, 300, 3)


def test_letterbox_round_trip_keeps_a_point() -> None:
    from hub.vision.people import _letterbox, _unmap_box

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    _canvas, scale, pad_x, pad_y = _letterbox(frame, 640)
    # A point in the middle of the original frame lands back on itself.
    mid_x = 320 * scale + pad_x
    mid_y = 240 * scale + pad_y
    x1, y1, x2, y2 = _unmap_box(
        np.array([mid_x, mid_y, mid_x + scale, mid_y + scale]),
        scale,
        pad_x,
        pad_y,
        640,
        480,
    )
    assert abs(x1 - 320) <= 1
    assert abs(y1 - 240) <= 1
    assert x2 > x1 and y2 > y1


def test_missing_frame_still_reserves_a_tile() -> None:
    wall = compose_wall([("Front door", None)], 80, 60)
    assert wall.shape == (60, 80, 3)
    assert int(wall[10, 10, 0]) == 0
