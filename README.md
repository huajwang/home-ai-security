# Home AI Security

Local-first home hub: doorway computer vision, HTTPS control, WebRTC intercom, stub lock adapter, and two Android apps (phone + indoor station). Remote access is VPN-only (Tailscale / WireGuard). No public port-forward.

This prototype grows out of the Week 5 YOLO doorway loop (`20_smart_security_starter.py`) but lives in this repo — the hub is the only process that opens the camera, microphone, speakers, and lock adapter.

## Product intent

This repo is a **step-by-step prototype of one house**, not the finished SKU. The goal is to **design and produce a competitive product** (local-first door station + indoor station + phone + hub): person-at-door, Talk, lock/unlock, arm/disarm, no cloud doorbell subscription.

Build and hardware choices should stay product-shaped: keep Unlock on the HTTPS control plane, keep Talk/media separate, use **adapters** (lock, later camera/RTSP) so a USB webcam and `StubLockAdapter` can be swapped for a PoE doorbell and a real deadbolt without rewriting the apps. Prefer local radios/APIs (Z-Wave, RTSP) over vendor clouds. Do not add Alexa/Google unlock or public port-forward as the remote path.

The Windows PC is a **lab bench**, not the SKU. Do not optimize the roadmap for “lift this venv onto another box.” Optimize for a **competitive appliance**: indoor hub (always-on, Ethernet, USB radios), PoE door station, indoor panel, phone app. On-device vision is a product feature (NPU-class SoC such as **RK3588** / Radxa ROCK 5T as the compute to design around). An x86 **N100** mini PC is only an optional engineering mule if we need the current Python stack running this week — it is not the product thesis. Accept RKNN/Linux carrier work when it makes a shippable hub, rather than staying on Intel because `pip install` is easier.

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
