"""Hub configuration. Environment variables override defaults."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("HUB_DATA_DIR", HUB_DIR / "data"))
SNAPSHOT_DIR = DATA_DIR / "snapshots"
CLIP_DIR = DATA_DIR / "clips"
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
# RTSP/HTTP URL wins over CAMERA_INDEX (Reolink: rtsp://user:pass@ip:554/h264Preview_01_sub).
CAMERA_URL = os.getenv("HUB_CAMERA_URL", "").strip()
# USB webcam for a second camera, such as the driveway. Empty leaves it off.
# "0" is /dev/video0. A path such as /dev/video0 is also accepted.
DRIVEWAY_CAMERA = os.getenv("HUB_DRIVEWAY_CAMERA", "").strip()
# Publish frames for the HDMI camera screen. The screen process is separate.
MONITOR_ENABLED = os.getenv("HUB_MONITOR", "0") not in {"0", "false", "False"}
MONITOR_DIR = Path(os.getenv("HUB_MONITOR_DIR", "/dev/shm/home-ai-wall"))
# A webcam on another computer can send frames to the monitor.
PC_CAMERA_ENABLED = os.getenv("HUB_PC_CAMERA", "0") not in {"0", "false", "False"}
PC_CAMERA_PORT = int(os.getenv("HUB_PC_CAMERA_PORT", "8091"))
PC_CAMERA_LABEL = os.getenv("HUB_PC_CAMERA_LABEL", "This PC")
DOORBELL_ENABLED = os.getenv("HUB_DOORBELL_ENABLED", "1" if CAMERA_URL else "0") not in {
    "0",
    "false",
    "False",
}
TALKBACK_ENABLED = os.getenv("HUB_TALKBACK_ENABLED", "1" if CAMERA_URL else "0") not in {
    "0",
    "false",
    "False",
}
ONVIF_PORT = int(os.getenv("HUB_ONVIF_PORT", "8000"))
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
# Empty uses the RK3588 model installed with the NPU package, when that file exists.
NPU_MODEL = os.getenv("HUB_NPU_MODEL", "").strip()

AUDIO_ENABLED = os.getenv("HUB_AUDIO_ENABLED", "1") not in {"0", "false", "False"}
AUDIO_SAMPLE_RATE = int(os.getenv("HUB_AUDIO_RATE", "48000"))
WEBRTC_MAX_WIDTH = int(os.getenv("HUB_WEBRTC_MAX_WIDTH", "640"))
WEBRTC_FPS = int(os.getenv("HUB_WEBRTC_FPS", "15"))
CLIP_MAX_SECONDS = float(os.getenv("HUB_CLIP_MAX_SECONDS", "60"))

# CH340 Zigbee coordinator (ZNP). Empty disables the bulb controller.
ZIGBEE_DEVICE = os.getenv("HUB_ZIGBEE_DEVICE", "").strip()
ZIGBEE_BAUD = int(os.getenv("HUB_ZIGBEE_BAUD", "115200"))
# Zooz Z-Wave stick. Empty keeps the in-memory stub lock.
ZWAVE_DEVICE = os.getenv("HUB_ZWAVE_DEVICE", "").strip()
ZWAVE_URL = os.getenv("HUB_ZWAVE_URL", "http://127.0.0.1:3091").strip()

LOGIN_RATE_LIMIT = int(os.getenv("HUB_LOGIN_RATE_LIMIT", "10"))
UNLOCK_RATE_LIMIT = int(os.getenv("HUB_UNLOCK_RATE_LIMIT", "5"))
RATE_WINDOW_SECONDS = int(os.getenv("HUB_RATE_WINDOW", "60"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    CERT_DIR.mkdir(parents=True, exist_ok=True)
