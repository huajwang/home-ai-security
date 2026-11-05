# Lovelace and the three clients

Home Assistant on the ROCK 5T is the only UI. The browser, the Android Companion app, and the iOS Companion app all open the same Lovelace dashboards.

## Addresses

| Where the phone is | URL |
|---|---|
| Home Wi-Fi | `http://<board LAN address>:8123` |
| Tailscale or WireGuard is up | The board's Tailscale name. If iOS rejects plain HTTP, run `tailscale serve` on the board so that name is HTTPS inside the tailnet only. |
| No tunnel installed | `https://rock.link.yaojiabuy.com` |

In each Companion app set the internal URL to the LAN address and the external URL to `https://rock.link.yaojiabuy.com`. A phone with Tailscale up should use the Tailscale name as its server URL so live video does not cross Aliyun. The wall display opens the LAN URL full screen.

`external_url` and `internal_url` are set in [deploy/rock5t/homeassistant/configuration.yaml](../deploy/rock5t/homeassistant/configuration.yaml). Change `internal_url` to this board's LAN address before the first start.

## Cameras

Install HACS, then the Frigate integration and the Frigate Card. Point the integration at `http://127.0.0.1:5000`.

On a Cloud Link session the card's live provider is MSE. That stream stays inside the HTTPS connection Caddy forwards to port 8123. WebRTC is for a client that can reach the board's UDP port 8555, which is the LAN and Tailscale path.

Replace the `REPLACE_*` RTSP URLs in [deploy/rock5t/frigate/config.yml](../deploy/rock5t/frigate/config.yml) before starting Frigate. Recordings go to `/mnt/hub-data/home-ai/frigate/media` on this board, which has no NVMe.

The doorbell button is the Reolink integration in Home Assistant, using the camera's HTTP API. Two-way talk and the spoken doorbell line use that integration's talk service, played from an automation. Frigate still records and detects on the RTSP sub-stream.

## Alarm, lock, siren

The manual alarm panel is `alarm_control_panel.alarm`. Alexa can arm and disarm it. The `lock` domain is not exposed to Alexa. "Alexa, turn on Front door lock" runs `script.lock_front_door`, which only calls `lock.lock`. Unlock stays on the Companion app, with the lock's PIN.

`binary_sensor.front_door_bolt` is on when the bolt is unlocked, so Alexa can be asked whether that sensor is open.

The Elegoo Mega stays on the lab PC. On that PC:

```powershell
python deploy/elegoo_alert.py --port-serial COM6
```

Set `ELEGOO_TOKEN` to the same value as `elegoo_token` in Home Assistant's `secrets.yaml`. The automations in [deploy/rock5t/homeassistant/automations.yaml](../deploy/rock5t/homeassistant/automations.yaml) post to `elegoo_url` when a person is at the door while armed, when the alarm is disarmed, and when the scene remote sends emergency. After ZHA pairing, replace `REPLACE_REMOTE_IEEE` with that remote.

Google Home control, when added later, uses `/api/google_assistant` on the same public name and the same rule: do not expose the `lock` domain. Camera tiles inside the Google Home app are a separate CameraStream integration and are not part of this stack. Sentence search of old hub events is not carried over.
