# Home AI Security - iOS Client (iPhone)

A companion React Native / Expo iOS client designed as a feature peer to the Android mobile app. Runs directly on your physical iPhone via **Expo Go** without requiring a Mac or Apple Developer account.

---

## 📱 Features

- **End-to-End Remote & LAN Access**: Connects securely over Tailscale (`https://100.87.220.55:8443`) or Home Wi-Fi (`https://10.0.0.83:8443`).
- **Perimeter Arm / Disarm**: Real-time arming status, siren active alarms, and Vision AI telemetry (FPS, person detection status, last person seen).
- **Biometric Smart Lock**: Door lock controls strictly enforced with **Face ID / Touch ID** or Station PIN confirmation before unlocking.
- **Zigbee Smart Lighting**: One-tap porch/room light control (`/v1/lights/on`, `/v1/lights/off`) and device pairing.
- **Driveway Camera Feed**: Live snapshot preview feed.
- **Home AI Assistant**: Chat with the in-process Qwen 2.5 LLM running on the ROCK 5T NPU for security briefings, status checks, and natural language device commands.
- **Security Events & AI Search**: Natural language event search (`/v1/events/search`) and full-screen event snapshot gallery.
- **Real-Time WebSockets**: Live event stream (`/v1/stream/events`) for instantaneous state and detection updates.

---

## 🚀 How to Run on Your iPhone (Testing)

### Step 1: Install Expo Go on iPhone
1. Open the **App Store** on your iPhone.
2. Search for and install **Expo Go** (published by 650 Industries, free).

### Step 2: Ensure Network Connectivity
Ensure your iPhone is connected to your **Home Wi-Fi** or has **Tailscale connected** to reach the ROCK 5T board at `100.87.220.55`.

*(Optional, for TLS trust)*:
If your Hub uses a self-signed or mkcert certificate:
- Open Safari on your iPhone and visit `https://100.87.220.55:8443/health`.
- If Safari shows "This Connection Is Not Private", tap **Show Details** → **visit this website**.
- Or AirDrop/email your `rootCA.pem` to your iPhone, tap **Install Profile**, then enable it under **Settings → General → About → Certificate Trust Settings**.

### Step 3: Start the Development Server on Windows
From this repository on your PC, open PowerShell and run:

```powershell
cd c:\data\github\home-ai-security\ios-app
npx expo start
```

### Step 4: Open on iPhone
- Open the **Camera app** on your iPhone and point it at the QR code displayed in the Windows terminal.
- Tap the notification banner that says **"Open in Expo Go"**.
- The app will load directly on your iPhone.

---

## 🔐 Default Login Credentials

- **Hub URL**: `https://100.87.220.55:8443` (Tailscale) or `https://10.0.0.83:8443` (LAN)
- **Username**: `owner`
- **Password**: `changeme`
