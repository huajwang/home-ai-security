"""Person face mask and covering detector.

Analyzes the head/face region of detected persons to identify whether they are wearing
a mask (surgical, cloth, N95, balaclava, or face covering).
Supports both heuristic multi-spectrum color/texture analysis and optional ONNX/YOLO models.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from hub import config


@dataclass(frozen=True)
class MaskResult:
    masked: bool
    confidence: float
    status: str  # "masked", "unmasked", or "unknown"
    details: str
    face_box: tuple[int, int, int, int] | None = None


_mask_detector: MaskDetector | None = None
_mask_detector_lock = threading.Lock()


def shared_mask_detector() -> MaskDetector:
    global _mask_detector
    with _mask_detector_lock:
        if _mask_detector is None:
            _mask_detector = MaskDetector()
        return _mask_detector


class MaskDetector:
    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path or config.MASK_MODEL
        self._custom_model: Any = None
        self._lock = threading.Lock()
        if self._model_path and Path(self._model_path).is_file():
            self._load_model(self._model_path)

    def _load_model(self, path: str) -> None:
        try:
            if path.endswith(".onnx"):
                self._custom_model = cv2.dnn.readNetFromONNX(path)
                print(f"Mask detector loaded ONNX model: {path}")
            elif path.endswith(".pt"):
                from ultralytics import YOLO

                self._custom_model = YOLO(path)
                print(f"Mask detector loaded YOLO model: {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to load mask model {path}: {exc}. Using computer vision fallback.")
            self._custom_model = None

    def detect_mask(
        self,
        frame: np.ndarray,
        person_box: tuple[int, int, int, int],
    ) -> MaskResult:
        if self._custom_model is not None:
            try:
                with self._lock:
                    return self._detect_with_model(frame, person_box)
            except Exception as exc:  # noqa: BLE001
                print(f"Custom mask model inference failed: {exc}")

        return detect_mask_heuristic(frame, person_box)

    def _detect_with_model(
        self, frame: np.ndarray, person_box: tuple[int, int, int, int]
    ) -> MaskResult:
        x1, y1, x2, y2 = person_box
        face_roi, face_box = extract_head_roi(frame, (x1, y1, x2, y2))
        if face_roi is None or face_roi.size == 0:
            return MaskResult(
                masked=False,
                confidence=0.0,
                status="unknown",
                details="no_face_roi",
                face_box=face_box,
            )

        if hasattr(self._custom_model, "predict"):  # YOLO
            results = self._custom_model.predict(face_roi, verbose=False)
            if results and len(results[0].boxes) > 0:
                box = results[0].boxes[0]
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                cls_name = str(results[0].names.get(cls_id, "")).lower()
                is_mask = "mask" in cls_name and "no" not in cls_name
                return MaskResult(
                    masked=is_mask and conf >= config.MASK_CONFIDENCE_THRESHOLD,
                    confidence=conf,
                    status="masked" if is_mask else "unmasked",
                    details=f"yolo_{cls_name}",
                    face_box=face_box,
                )

        # Fallback to heuristic
        return detect_mask_heuristic(frame, person_box)


def extract_head_roi(
    frame: np.ndarray,
    person_box: tuple[int, int, int, int],
) -> tuple[np.ndarray | None, tuple[int, int, int, int] | None]:
    """Extract the upper head/face region from a person bounding box."""
    fh, fw = frame.shape[:2]
    px1, py1, px2, py2 = person_box
    pw = max(1, px2 - px1)
    ph = max(1, py2 - py1)

    # The head/face is typically in the top ~30% of the person box, centered horizontally
    head_y1 = max(0, py1)
    head_y2 = min(fh, py1 + int(ph * 0.35))
    head_x1 = max(0, px1 + int(pw * 0.15))
    head_x2 = min(fw, px2 - int(pw * 0.15))

    if head_y2 - head_y1 < 15 or head_x2 - head_x1 < 15:
        return None, None

    head_roi = frame[head_y1:head_y2, head_x1:head_x2]
    return head_roi, (head_x1, head_y1, head_x2, head_y2)


def detect_mask_heuristic(
    frame: np.ndarray,
    person_box: tuple[int, int, int, int],
) -> MaskResult:
    """Analyze head ROI using skin tone segmentation, mask color patterns, and facial zones."""
    head_roi, face_box = extract_head_roi(frame, person_box)
    if head_roi is None or head_roi.size == 0:
        return MaskResult(
            masked=False,
            confidence=0.0,
            status="unknown",
            details="head_too_small",
            face_box=face_box,
        )

    hh, hw = head_roi.shape[:2]
    ycrcb = cv2.cvtColor(head_roi, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(head_roi, cv2.COLOR_BGR2HSV)

    # 1. Robust Skin segmentation (YCrCb + HSV)
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    h_chan = hsv[:, :, 0]
    s_chan = hsv[:, :, 1]
    v_chan = hsv[:, :, 2]

    is_skin = (
        (cr >= 130)
        & (cr <= 175)
        & (cb >= 77)
        & (cb <= 128)
        & ((h_chan <= 25) | (h_chan >= 165))
        & (s_chan >= 20)
        & (v_chan >= 40)
    )

    # Face Zones:
    # Upper Face: 10% to 45% of head height (eyes, forehead)
    # Lower Face: 45% to 90% of head height (nose, mouth, chin)
    y_up_start, y_up_end = int(hh * 0.10), max(1, int(hh * 0.45))
    y_low_start, y_low_end = y_up_end, max(y_up_end + 1, int(hh * 0.90))

    up_skin = float(np.mean(is_skin[y_up_start:y_up_end, :]))
    low_skin = float(np.mean(is_skin[y_low_start:y_low_end, :]))

    # 2. Surgical / Blue / Teal / Cyan mask detection
    # Typical surgical mask hue: ~75-125 in OpenCV (150-250 deg in standard HSV)
    is_blue_mask = (
        (h_chan >= 75)
        & (h_chan <= 125)
        & (s_chan >= 30)
        & (v_chan >= 45)
    )
    low_blue = float(np.mean(is_blue_mask[y_low_start:y_low_end, :]))

    # 3. Surgical Green mask detection: H in [35, 75]
    is_green_mask = (
        (h_chan >= 35)
        & (h_chan <= 75)
        & (s_chan >= 35)
        & (v_chan >= 45)
    )
    low_green = float(np.mean(is_green_mask[y_low_start:y_low_end, :]))

    # 4. White / N95 mask detection: low saturation, high brightness
    is_white_mask = (s_chan <= 30) & (v_chan >= 180)
    low_white = float(np.mean(is_white_mask[y_low_start:y_low_end, :]))

    # 5. Black / Dark mask or Balaclava / Ski mask
    is_dark = (v_chan <= 60) | ((v_chan <= 80) & (s_chan <= 40))
    low_dark = float(np.mean(is_dark[y_low_start:y_low_end, :]))
    up_dark = float(np.mean(is_dark[y_up_start:y_up_end, :]))

    # 6. Horizontal edge along nose bridge / mask rim (y around 40-50%)
    gray = cv2.cvtColor(head_roi, cv2.COLOR_BGR2GRAY)
    sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    ridge_roi = np.abs(sobel_y[max(0, y_up_end - 5) : min(hh, y_up_end + 10), :])
    ridge_score = float(np.mean(ridge_roi)) if ridge_roi.size > 0 else 0.0

    # Decision Logic:
    score = 0.0
    details = "unmasked_face"

    # Scenario A: Surgical blue / cyan mask
    if low_blue >= 0.20 and low_skin < 0.25:
        score = min(0.98, 0.65 + low_blue * 0.45)
        details = "surgical_blue_mask"

    # Scenario B: Surgical green mask
    elif low_green >= 0.20 and low_skin < 0.25:
        score = min(0.98, 0.65 + low_green * 0.45)
        details = "surgical_green_mask"

    # Scenario C: White / N95 mask
    elif low_white >= 0.25 and low_skin < 0.25 and up_skin >= 0.20:
        score = min(0.96, 0.60 + low_white * 0.40)
        details = "white_n95_mask"

    # Scenario D: Dark mask with uncovered forehead/eyes
    elif low_dark >= 0.35 and up_skin >= 0.25 and low_skin < 0.20:
        score = min(0.98, 0.60 + low_dark * 0.45)
        details = "black_cloth_mask"

    # Scenario E: Balaclava / Full face covering (both upper and lower mostly dark, very low skin)
    elif low_dark >= 0.45 and up_dark >= 0.40 and (up_skin + low_skin) < 0.25:
        score = min(0.99, 0.70 + ((low_dark + up_dark) / 2) * 0.30)
        details = "balaclava_or_ski_mask"

    # Scenario F: Generic mask - upper face has visible skin, lower face has sharp drop in skin
    elif up_skin >= 0.30 and low_skin < 0.12:
        skin_contrast = up_skin - low_skin
        score = min(0.92, 0.50 + skin_contrast * 0.50)
        details = "covered_lower_face"

    # Scenario G: Unmasked person (both upper and lower have healthy skin coverage)
    elif low_skin >= 0.30 and (low_skin / max(up_skin, 0.05)) >= 0.60:
        score = max(0.02, 1.0 - low_skin) * 0.3  # Very low mask score
        details = "unmasked_face"

    else:
        # Ambiguous / lower confidence
        score = 0.25
        details = "unclear_face_features"

    # Adjust slightly if there's a strong horizontal boundary ridge across the nose
    if ridge_score > 35.0 and details != "unmasked_face" and score >= 0.40:
        score = min(0.99, score + 0.08)

    threshold = config.MASK_CONFIDENCE_THRESHOLD
    is_masked = score >= threshold

    return MaskResult(
        masked=is_masked,
        confidence=round(score, 3),
        status="masked" if is_masked else "unmasked",
        details=details,
        face_box=face_box,
    )
