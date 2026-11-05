# Home AI Security

The ROCK 5T runs Radxa Debian and Docker. Home Assistant is the UI and the automation engine. Frigate uses the RK3588 NPU for detection and records to the NVMe. Zigbee is ZHA inside Home Assistant. The Zooz stick is Z-Wave JS UI.

Remote access is Tailscale or WireGuard when the phone has a tunnel, and the existing Cloud Link relay when it does not. There is no port forward. Alexa can lock, arm, and disarm. It cannot unlock. Unlock stays in the Companion app and requires the lock PIN.

## On the board

Follow [docs/ha-cutover.md](docs/ha-cutover.md). The Compose file is [deploy/rock5t/compose.yaml](deploy/rock5t/compose.yaml). Lovelace, the Companion apps, and the siren are described in [docs/lovelace.md](docs/lovelace.md). Alexa is [docs/alexa.md](docs/alexa.md).

The Buildroot tree under `os/buildroot/` is an earlier image. The card in the board now is the 32 GB Debian card.
