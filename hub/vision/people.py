"""One person detector for every camera.

The RK3588 neural processor is used when its model is installed.
Otherwise one CPU model is shared, so the doorbell and driveway do not each load a copy.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import cv2
import numpy as np

from hub import config

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
_MODEL_CANDIDATES = (
    "/usr/share/rknn_model_zoo/examples/yolov8/model/yolov8.rknn",
    "/usr/share/rknn_model_zoo/examples/yolov8/model/yolov8n.rknn",
)
_IMAGE_SIZE = 640
_NMS_THRESHOLD = 0.45
_PERSON = "person"

_detector: PeopleDetector | None = None
_detector_lock = threading.Lock()


def shared_detector() -> PeopleDetector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = _load_detector()
        return _detector


class PeopleDetector:
    def detect(self, frame: np.ndarray) -> list[tuple[str, float, int, int, int, int]]:
        raise NotImplementedError


class NpuPeopleDetector(PeopleDetector):
    def __init__(self, model_path: str) -> None:
        RKNNLite = _import_rknn()
        self._rknn = RKNNLite()
        if self._rknn.load_rknn(model_path) != 0:
            raise RuntimeError(f"Could not load NPU model {model_path}")
        if self._rknn.init_runtime() != 0:
            raise RuntimeError("Could not start the neural processor")
        self._infer_lock = threading.Lock()
        print(f"Person detection using the neural processor ({model_path})")

    def detect(self, frame: np.ndarray) -> list[tuple[str, float, int, int, int, int]]:
        image, scale, pad_x, pad_y = _letterbox(frame, _IMAGE_SIZE)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        batch = np.expand_dims(rgb, 0)
        try:
            with self._infer_lock:
                outputs = self._rknn.inference(inputs=[batch])
        except Exception as exc:  # noqa: BLE001
            print(f"Neural processor inference failed: {exc}")
            return []
        if not outputs:
            return []
        boxes, classes, scores = _post_process(outputs)
        if boxes is None:
            return []
        found: list[tuple[str, float, int, int, int, int]] = []
        for box, class_id, score in zip(boxes, classes, scores):
            label = _class_name(int(class_id))
            if label not in config.ALLOWED_LABELS or float(score) < config.CONFIDENCE_THRESHOLD:
                continue
            x1, y1, x2, y2 = _unmap_box(box, scale, pad_x, pad_y, frame.shape[1], frame.shape[0])
            found.append((label, float(score), x1, y1, x2, y2))
        return found


class CpuPeopleDetector(PeopleDetector):
    """One shared CPU model, used only when the neural processor model is absent."""

    def __init__(self) -> None:
        from ultralytics import YOLO

        self._model = YOLO(config.YOLO_MODEL)
        self._infer_lock = threading.Lock()
        print(f"Person detection using the CPU ({config.YOLO_MODEL})")

    def detect(self, frame: np.ndarray) -> list[tuple[str, float, int, int, int, int]]:
        with self._infer_lock:
            results = self._model(frame, verbose=False)
        result = results[0]
        names = result.names
        boxes = result.boxes
        found: list[tuple[str, float, int, int, int, int]] = []
        if boxes is None:
            return found
        for box in boxes:
            label = str(names[int(box.cls[0])]).strip()
            confidence = float(box.conf[0])
            if label not in config.ALLOWED_LABELS or confidence < config.CONFIDENCE_THRESHOLD:
                continue
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
            found.append((label, confidence, x1, y1, x2, y2))
        return found


def _load_detector() -> PeopleDetector:
    model_path = _npu_model_path()
    if model_path is not None:
        try:
            return NpuPeopleDetector(str(model_path))
        except Exception as exc:  # noqa: BLE001
            print(f"Neural processor idle: {exc}")
    return CpuPeopleDetector()


def _npu_model_path() -> Path | None:
    configured = config.NPU_MODEL
    candidates = [Path(configured)] if configured else []
    candidates.extend(Path(path) for path in _MODEL_CANDIDATES)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _import_rknn():
    try:
        from rknnlite.api import RKNNLite
    except ImportError:
        if _DIST_PACKAGES not in sys.path:
            sys.path.append(_DIST_PACKAGES)
        from rknnlite.api import RKNNLite
    return RKNNLite


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    pad_x = (size - resized_w) // 2
    pad_y = (size - resized_h) // 2
    canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized
    return canvas, scale, pad_x, pad_y


def _unmap_box(
    box: np.ndarray, scale: float, pad_x: int, pad_y: int, width: int, height: int
) -> tuple[int, int, int, int]:
    x1 = int((float(box[0]) - pad_x) / scale)
    y1 = int((float(box[1]) - pad_y) / scale)
    x2 = int((float(box[2]) - pad_x) / scale)
    y2 = int((float(box[3]) - pad_y) / scale)
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(0, min(width - 1, x2)),
        max(0, min(height - 1, y2)),
    )


def _class_name(class_id: int) -> str:
    names = (
        "person", "bicycle", "car", "motorbike", "aeroplane", "bus", "train", "truck", "boat",
        "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
        "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
        "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
        "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
        "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
        "sofa", "pottedplant", "bed", "diningtable", "toilet", "tvmonitor", "laptop", "mouse",
        "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
        "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
    )
    if 0 <= class_id < len(names):
        return names[class_id]
    return ""


def _dfl(position: np.ndarray) -> np.ndarray:
    count, channels, height, width = position.shape
    bins = channels // 4
    values = position.reshape(count, 4, bins, height, width)
    values = values - values.max(axis=2, keepdims=True)
    weights = np.exp(values)
    weights = weights / weights.sum(axis=2, keepdims=True)
    steps = np.arange(bins, dtype=np.float32).reshape(1, 1, bins, 1, 1)
    return (weights * steps).sum(axis=2)


def _box_process(position: np.ndarray) -> np.ndarray:
    grid_h, grid_w = position.shape[2:4]
    column, row = np.meshgrid(np.arange(0, grid_w), np.arange(0, grid_h))
    grid = np.concatenate(
        (column.reshape(1, 1, grid_h, grid_w), row.reshape(1, 1, grid_h, grid_w)),
        axis=1,
    ).astype(np.float32)
    stride = np.array(
        [_IMAGE_SIZE / grid_h, _IMAGE_SIZE / grid_w], dtype=np.float32
    ).reshape(1, 2, 1, 1)
    distance = _dfl(position)
    xy1 = grid + 0.5 - distance[:, 0:2, :, :]
    xy2 = grid + 0.5 + distance[:, 2:4, :, :]
    return np.concatenate((xy1 * stride, xy2 * stride), axis=1)


def _flatten(tensor: np.ndarray) -> np.ndarray:
    channels = tensor.shape[1]
    return tensor.transpose(0, 2, 3, 1).reshape(-1, channels)


def _nms(boxes: np.ndarray, scores: np.ndarray) -> np.ndarray:
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[current], x1[rest])
        yy1 = np.maximum(y1[current], y1[rest])
        xx2 = np.minimum(x2[current], x2[rest])
        yy2 = np.minimum(y2[current], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[current] + areas[rest] - inter
        overlap = inter / np.maximum(union, 1e-6)
        order = rest[overlap <= _NMS_THRESHOLD]
    return np.array(keep, dtype=np.int64)


def _post_process(outputs: list[np.ndarray]):
    branches = 3
    per_branch = len(outputs) // branches
    boxes_list = []
    class_list = []
    score_list = []
    for index in range(branches):
        position = outputs[per_branch * index]
        classes = outputs[per_branch * index + 1]
        boxes_list.append(_flatten(_box_process(position)))
        class_list.append(_flatten(classes))
        score_list.append(np.ones((classes.shape[0], 1, classes.shape[2], classes.shape[3]), dtype=np.float32))
        score_list[-1] = _flatten(score_list[-1])
    boxes = np.concatenate(boxes_list)
    class_probs = np.concatenate(class_list)
    objectness = np.concatenate(score_list).reshape(-1)
    class_score = class_probs.max(axis=-1)
    class_id = class_probs.argmax(axis=-1)
    keep = np.where(class_score * objectness >= config.CONFIDENCE_THRESHOLD)[0]
    if keep.size == 0:
        return None, None, None
    boxes = boxes[keep]
    class_id = class_id[keep]
    scores = (class_score * objectness)[keep]
    kept_boxes = []
    kept_classes = []
    kept_scores = []
    for label in set(class_id.tolist()):
        chosen = np.where(class_id == label)[0]
        survivors = _nms(boxes[chosen], scores[chosen])
        if survivors.size == 0:
            continue
        kept_boxes.append(boxes[chosen][survivors])
        kept_classes.append(class_id[chosen][survivors])
        kept_scores.append(scores[chosen][survivors])
    if not kept_boxes:
        return None, None, None
    return np.concatenate(kept_boxes), np.concatenate(kept_classes), np.concatenate(kept_scores)
