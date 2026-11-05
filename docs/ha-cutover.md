# Cut over the ROCK 5T to Home Assistant

The board that is running is the 32 GB Radxa Debian card. The Buildroot image in `os/buildroot/` is not this boot disk. Do this in order. Stopping the hub before Frigate and Lovelace answer, or pointing Cloud Link at Caddy while the hub still owns port 8444, takes Alexa and the cameras down together.

## 1. Check the kernel and the disk

On the board:

```bash
uname -r
ls -l /dev/dri /dev/dma_heap /dev/rga /dev/mpp_service
sudo cat /sys/kernel/debug/rknpu/version
```

`uname -r` should contain `rockchip` or `rk2410`. `/dev/dri` should list `renderD128` and `renderD129`. The RKNPU line should be `v0.9.2` or newer.

This board has no NVMe. The 22 GB `/mnt/hub-data` partition is the data disk, and Docker's data-root belongs there too because `/` only has about 1 GB free. Create:

```bash
sudo mkdir -p /mnt/hub-data/home-ai/homeassistant \
  /mnt/hub-data/home-ai/frigate/media \
  /mnt/hub-data/home-ai/mosquitto \
  /mnt/hub-data/home-ai/zwave-js \
  /mnt/hub-data/docker
```

Copy [deploy/rock5t/homeassistant/configuration.yaml](../deploy/rock5t/homeassistant/configuration.yaml) and [automations.yaml](../deploy/rock5t/homeassistant/automations.yaml) into `/mnt/hub-data/home-ai/homeassistant/`. Copy `secrets.yaml.example` to `secrets.yaml` and fill it in. Put the real RTSP URLs into [deploy/rock5t/frigate/config.yml](../deploy/rock5t/frigate/config.yml).

Install Docker, and install Tailscale on the board if it is not already there. `tailscale serve` is only needed when an iPhone rejects `http://100.x:8123`.

## 2. Start the stack without taking the radios or port 8444

From the repo root on the board:

```bash
docker compose -f deploy/rock5t/compose.yaml up -d homeassistant mosquitto frigate
```

Leave `zwave-js-ui` and the `link` profile stopped. The hub process still holds `/dev/ttyUSB0`, `/dev/ttyACM0`, and `127.0.0.1:8444`. Do not add the ZHA integration yet.

Open `http://<LAN>:8123`, finish onboarding, install HACS, the Frigate integration (`http://127.0.0.1:5000`), and the Frigate Card. Confirm one camera on the LAN. Then confirm the same card over Tailscale. MSE is the live provider for the public URL; do not switch the card to WebRTC until the phone is on Tailscale.

## 3. Hand the radios to Home Assistant

Stop the hub and the old Z-Wave process so the serial ports are free:

```bash
sudo systemctl stop home-ai-hub home-ai-voice home-ai-powerconf || true
```

Copy the four keys from the hub's `hub/data/zwave/security-keys.json` (`S0_Legacy`, `S2_Unauthenticated`, `S2_Authenticated`, `S2_AccessControl`). Start Z-Wave JS UI and paste those keys in its settings before it interviews the stick:

```bash
docker compose -f deploy/rock5t/compose.yaml up -d zwave-js-ui
```

The UI is `http://127.0.0.1:8091`. In Home Assistant, add the Z-Wave JS integration at `ws://127.0.0.1:3000`. The lock network lives on the Zooz stick; new keys would force a re-include.

Add the ZHA integration on `/dev/ttyUSB0` at 115200 baud. The hub's `zigbee.db` is not a ZHA database. Pair the bulbs, the scene remote, and the door sensors again. Set `REPLACE_REMOTE_IEEE` in `automations.yaml` to the remote that was just paired. Add the Reolink integration for the doorbell button.

Unlock the bolt from the Companion app with the PIN. Confirm Alexa is not involved yet.

## 4. Point Cloud Link and Alexa at Home Assistant

Start Caddy only after the hub is stopped:

```bash
cd /home/radxa/home-ai-security
docker compose -f deploy/rock5t/compose.yaml --profile link up -d caddy
.venv/bin/pip install -r requirements.txt
sudo cp deploy/rock5t/cloudlink-agent.service /etc/systemd/system/cloudlink-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now cloudlink-agent
```

`hub.env` still supplies `HUB_LINK_URL`, `HUB_LINK_HOSTNAME`, and `HUB_LINK_FERNET_KEY`. The agent dials Aliyun and splices `rock.link.yaojiabuy.com` to `127.0.0.1:8444`. Caddy presents the existing Let's Encrypt certificate and proxies to port 8123, including WebSockets.

Deploy [link/alexa_forwarder/lambda_function.py](../link/alexa_forwarder/lambda_function.py). Set `HUB_URL` to `https://rock.link.yaojiabuy.com/api/alexa/smart_home` and `HA_TOKEN` to a Home Assistant long-lived token. In the Alexa skill, set account linking to Home Assistant:

| Field | Value |
|---|---|
| Authorization URI | `https://rock.link.yaojiabuy.com/auth/authorize` |
| Access Token URI | `https://rock.link.yaojiabuy.com/auth/token` |
| Client ID | the `alexa_client_id` secret |
| Client secret | the `alexa_client_secret` secret |

Disable the skill, enable it, and sign in with the Home Assistant user. Say "Alexa, discover devices." Lights, the alarm, door sensors, and "Front door lock" should appear. "Alexa, unlock" must not find an unlock action. Discover from a phone that has no Tailscale and confirm the Frigate card plays over MSE.

## 5. What stays and what is gone

Tailscale is installed on Debian and does not depend on the hub. The Aliyun relay process (`python -m link`) stays. Google Home can be added on `/api/google_assistant` after this path works; do not expose `lock` there either. The old `/v1` API, the custom phone apps, the PowerConf voice satellite, and Qwen are removed from this repo.
