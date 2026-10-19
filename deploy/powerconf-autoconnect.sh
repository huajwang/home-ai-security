#!/bin/bash
# Connect the paired PowerConf whenever it powers on, then route its mic and speaker.
MAC="${POWERCONF_BT:-90:BF:D9:61:0C:E4}"
ROUTE=/home/radxa/home-ai-security/deploy/powerconf-route.sh
RUNTIME=(env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus)
was_up=0

bluetoothctl trust "$MAC" >/dev/null 2>&1 || true

while true; do
  if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
    if [ "$was_up" -eq 0 ]; then
      /usr/sbin/runuser -u radxa -- "${RUNTIME[@]}" bash "$ROUTE" || true
      if /usr/sbin/runuser -u radxa -- "${RUNTIME[@]}" wpctl status | grep -q "Anker PowerConf"; then
        systemctl try-restart home-ai-voice.service || true
        was_up=1
      fi
    fi
    sleep 10
  else
    was_up=0
    bluetoothctl --timeout 10 connect "$MAC" >/dev/null 2>&1 || true
    if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Connected: yes"; then
      continue
    fi
    sleep 5
  fi
done
