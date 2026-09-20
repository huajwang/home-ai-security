# Prototype setup

## Hub on the desktop PC

From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m hub
```

Defaults:

- HTTPS on `0.0.0.0:8443`
- First owner: `owner` / `changeme` (set `HUB_OWNER_USERNAME` / `HUB_OWNER_PASSWORD` before the first start)
- Camera index `0` (same idea as Week 5 `camera_index`)
- YOLO `yolov8n.pt` (downloaded on first vision start)
- PC default microphone and speakers for intercom

Useful environment variables:

| Variable | Meaning |
|---|---|
| `HUB_PORT` | TLS port (default 8443) |
| `HUB_VISION_ENABLED` | `0` to run API/lock without a camera |
| `HUB_VISION_DEBUG_WINDOW` | `1` to show the OpenCV debug window |
| `HUB_USE_ROI` | `1` to enable the doorway box |
| `HUB_ROI_X1` … `HUB_ROI_Y2` | ROI coordinates from Program 20 |
| `HUB_AUDIO_ENABLED` | `0` if mic/speakers fail to open |
| `HUB_JWT_SECRET` | Optional; otherwise generated and stored in SQLite |
| `HUB_CAMERA_INDEX` | Webcam index (ignored if `HUB_CAMERA_URL` is set) |
| `HUB_CAMERA_URL` | RTSP/HTTP camera URL (Reolink sub-stream), e.g. `rtsp://user:pass@10.0.0.50:554/h264Preview_01_sub` |
| `HUB_DOORBELL_ENABLED` | `0` to skip ONVIF doorbell-button listening |
| `HUB_TALKBACK_ENABLED` | `0` to keep Talk audio on the PC speakers instead of the doorbell |
| `HUB_ONVIF_PORT` | ONVIF port (default 8000) |

Dev intercom probe (not the product UI): open `https://localhost:8443/dev/call` after trusting the cert.

## mkcert (Android and Tailscale hostnames)

The hub writes a self-signed `certs/hub.pem` on first run. Android will reject that unless you install a **user CA**. Use [mkcert](https://github.com/FiloSottile/mkcert):

```powershell
mkcert -install
mkcert -cert-file certs/hub.pem -key-file certs/hub-key.pem localhost 127.0.0.1 YOUR-LAN-IP YOUR-TAILSCALE-NAME
```

Replace `YOUR-LAN-IP` (from `ipconfig`) and `YOUR-TAILSCALE-NAME` (for example `desktop.tailnet-name.ts.net`). Restart the hub so it loads the new files.

On each Android device:

1. Install the mkcert **local CA** (`mkcert -CAROOT` then copy `rootCA.pem`)
2. Settings → Security → Install a certificate → CA certificate
3. The apps already trust user CAs via `network_security_config.xml`

Do not port-forward 8443 to the public internet.

## Tailscale / WireGuard (only remote path)

1. Install Tailscale on the PC, phone, and tablet. Sign into the same tailnet.
2. Use the hub’s Tailscale name or 100.x address in the app login field: `https://desktop.tailnet-name.ts.net:8443`
3. Include that hostname in the mkcert SAN list.
4. If Tailscale is down, the apps still work on home LAN with the LAN IP.

The hub does not implement a cloud relay.

## Android apps

Open `android/` in Android Studio, let it download the Gradle wrapper, then run:

- `phone` — `com.homeai.security.phone` (event list first, biometric unlock when available)
- `station` — `com.homeai.security.station` (large Talk / Unlock / Arm, PIN confirm; default PIN `1234`)

Both share `:shared` (API client + WebRTC). Grant microphone permission before Talk.

Login fields: hub URL, `owner`, password.

## Lock adapter swap

v1 ships `StubLockAdapter` (in-memory locked/unlocked + SQLite audit). To attach a certified lock later, implement `LockAdapter` in [hub/devices/lock.py](../hub/devices/lock.py) and return it from `build_lock_adapter()`:

```python
def build_lock_adapter(store: Store) -> LockAdapter:
    # return NukiLockAdapter(store, token=os.environ["NUKI_TOKEN"])
    return StubLockAdapter(store)
```

Keep unlock on the HTTPS control plane only. Do not add unlock to the WebRTC data channel.

## Windows firewall

Allow inbound TCP 8443 on the private network profile so the tablet/phone can reach the hub. Do not create a public/WAN rule.
