#!/bin/bash
# Enable BlueZ reconnect and start the PowerConf watcher. Run as root on the ROCK 5T.
set -eu
ROOT=/home/radxa/home-ai-security/deploy
chmod 755 "$ROOT/powerconf-autoconnect.sh" "$ROOT/powerconf-route.sh"
python3 - <<'PY'
from pathlib import Path
path = Path("/etc/bluetooth/main.conf")
text = path.read_text()
lines = text.splitlines()
if any(line.strip().startswith("ReconnectAttempts=") for line in lines):
    print("policy-present")
else:
    block = "AutoEnable=true\nReconnectAttempts=7\nReconnectIntervals=1,2,4,8,16,32,64\n"
    if "[Policy]" in text:
        text = text.replace("[Policy]\n", "[Policy]\n" + block, 1)
    else:
        text += "\n[Policy]\n" + block
    path.write_text(text)
    print("policy-updated")
PY
cp "$ROOT/home-ai-powerconf.service" /etc/systemd/system/home-ai-powerconf.service
systemctl daemon-reload
systemctl restart bluetooth
systemctl enable --now home-ai-powerconf.service
systemctl restart home-ai-powerconf.service
