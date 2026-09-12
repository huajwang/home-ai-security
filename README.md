# Home AI Security

Local-first home hub: doorway computer vision, HTTPS control, WebRTC intercom, stub lock adapter, and two Android apps (phone + indoor station). Remote access is VPN-only (Tailscale / WireGuard). No public port-forward.

This prototype grows out of the Week 5 YOLO doorway loop (`20_smart_security_starter.py`) but lives in this repo — the hub is the only process that opens the camera, microphone, speakers, and lock adapter.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m hub
```

Sign in as `owner` / `changeme` (change this). HTTPS listens on port **8443**.

- API contract: [docs/v1-api.md](docs/v1-api.md)
- TLS, Tailscale, Android, lock swap: [docs/setup.md](docs/setup.md)
- Android project: [android/README.md](android/README.md)

## v1 cut

**In:** person-at-door events + snapshots, arm/disarm, WebRTC talk via the PC camera/mic/speakers, lock adapter + stub, phone APK, tablet station APK, mkcert TLS, Tailscale remote.

**Out:** face ID, vendor lock SDKs, 24/7 recording, FCM, custom doorbell hardware, cloud relay.
