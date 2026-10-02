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


def test_missing_frame_still_reserves_a_tile() -> None:
    wall = compose_wall([("Front door", None)], 80, 60)
    assert wall.shape == (60, 80, 3)
    assert int(wall[10, 10, 0]) == 0
