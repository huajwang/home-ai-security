#!/bin/bash
# Connect the paired PowerConf and select its headset profile (microphone and speaker).
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
MAC="${POWERCONF_BT:-90:BF:D9:61:0C:E4}"

bluetoothctl connect "$MAC" >/dev/null 2>&1 || true
sleep 2

python3 - <<'PY'
import re
import subprocess
import time

def status() -> str:
    return subprocess.check_output(["wpctl", "status"], text=True, errors="replace")

text = status()
device_id = None
for line in text.splitlines():
    if "Anker PowerConf" in line and "bluez" in line:
        match = re.search(r"(\d+)\.", line)
        if match:
            device_id = match.group(1)
            break
if device_id is None:
    raise SystemExit(0)

for profile in ("261", "headset-head-unit-msbc", "3", "headset-head-unit"):
    result = subprocess.run(["wpctl", "set-profile", device_id, profile], capture_output=True)
    if result.returncode == 0:
        break
time.sleep(1)

section = None
for line in status().splitlines():
    if "Sinks:" in line:
        section = "sink"
        continue
    if "Sources:" in line:
        section = "source"
        continue
    if "endpoints" in line or "Video" in line:
        section = None
    if section and "Anker PowerConf" in line:
        match = re.search(r"(\d+)\.", line)
        if match:
            subprocess.run(["wpctl", "set-default", match.group(1)], check=False)
PY
