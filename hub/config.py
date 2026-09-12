"""Hub configuration. Environment variables override defaults."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("HUB_DATA_DIR", HUB_DIR / "data"))
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DB_PATH = Path(os.getenv("HUB_DB_PATH", DATA_DIR / "hub.db"))
CERT_DIR = Path(os.getenv("HUB_CERT_DIR", ROOT / "certs"))
CERT_FILE = CERT_DIR / "hub.pem"
KEY_FILE = CERT_DIR / "hub-key.pem"

HOST = os.getenv("HUB_HOST", "0.0.0.0")
PORT = int(os.getenv("HUB_PORT", "8443"))
HOME_NAME = os.getenv("HUB_HOME_NAME", "Home")

JWT_SECRET = os.getenv("HUB_JWT_SECRET", "").strip()
ACCESS_TOKEN_MINUTES = int(os.getenv("HUB_ACCESS_MINUTES", "480"))
REFRESH_TOKEN_DAYS = int(os.getenv("HUB_REFRESH_DAYS", "30"))

OWNER_USERNAME = os.getenv("HUB_OWNER_USERNAME", "owner")
OWNER_PASSWORD = os.getenv("HUB_OWNER_PASSWORD", "changeme")

VISION_ENABLED = os.getenv("HUB_VISION_ENABLED", "1") not in {"0", "false", "False"}
VISION_DEBUG_WINDOW = os.getenv("HUB_VISION_DEBUG_WINDOW", "0") not in {"0", "false", "False"}
CAMERA_INDEX = int(os.getenv("HUB_CAMERA_INDEX", "0"))
ALLOWED_LABELS = {
    item.strip()
    for item in os.getenv("HUB_ALLOWED_LABELS", "person").split(",")
    if item.strip()
}
CONFIDENCE_THRESHOLD = float(os.getenv("HUB_CONFIDENCE_THRESHOLD", "0.50"))
FRAMES_REQUIRED_FOR_ALERT = int(os.getenv("HUB_FRAMES_REQUIRED", "5"))
ALARM_COOLDOWN_SECONDS = float(os.getenv("HUB_ALARM_COOLDOWN", "3.0"))
USE_ROI = os.getenv("HUB_USE_ROI", "0") not in {"0", "false", "False"}
ROI = (
    int(os.getenv("HUB_ROI_X1", "200")),
    int(os.getenv("HUB_ROI_Y1", "100")),
    int(os.getenv("HUB_ROI_X2", "440")),
    int(os.getenv("HUB_ROI_Y2", "360")),
)
YOLO_MODEL = os.getenv("HUB_YOLO_MODEL", "yolov8n.pt")

AUDIO_ENABLED = os.getenv("HUB_AUDIO_ENABLED", "1") not in {"0", "false", "False"}
AUDIO_SAMPLE_RATE = int(os.getenv("HUB_AUDIO_RATE", "48000"))
WEBRTC_MAX_WIDTH = int(os.getenv("HUB_WEBRTC_MAX_WIDTH", "640"))
WEBRTC_FPS = int(os.getenv("HUB_WEBRTC_FPS", "15"))

LOGIN_RATE_LIMIT = int(os.getenv("HUB_LOGIN_RATE_LIMIT", "10"))
UNLOCK_RATE_LIMIT = int(os.getenv("HUB_UNLOCK_RATE_LIMIT", "5"))
RATE_WINDOW_SECONDS = int(os.getenv("HUB_RATE_WINDOW", "60"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    CERT_DIR.mkdir(parents=True, exist_ok=True)
