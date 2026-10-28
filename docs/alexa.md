# Alexa lights through Cloud Link

Alexa can turn paired Zigbee bulbs on and off, arm and disarm the alarm, lock the front door, and report door and lock state. It cannot unlock. This is a private development skill for one house. It is not certified, and it is not published in the Alexa skill store.

The spoken audio never reaches the house. The Echo Dot sends it to Alexa cloud. What comes back is a small JSON directive. The Aliyun relay splices the TLS connection and does not decrypt it. The ROCK 5T is the only machine that reads the Zigbee database or talks to a bulb.

`LINK_REGION` stays `cn`. The older `/voice` path in `link/voice.py` still returns 503 in that region. Alexa does not use that path.

## Who does what

| Piece | Role |
|---|---|
| Echo Dot | Microphone and speaker. It sends speech to Alexa cloud and plays the chime. It has no path to the bulb or the hub. |
| Alexa app | Enables the development skill, opens the hub login, and lists devices after a successful discovery. Renaming a device here changes the words you say. It does not change the IEEE address. |
| Alexa cloud | Turns speech into a Smart Home directive. Stores the linked account token and, after discovery, the bulb name and `endpointId`. Invokes the Lambda function. It does not scan Zigbee or the home LAN. |
| AWS Lambda `home-ai-alexa` | Runs in us-east-1. Alexa invokes it directly, so the request has no Alexa HTTPS signature. The function posts the same JSON to the hub with the forwarder header. |
| Aliyun Cloud Link | `8.129.103.161`, public name `rock.link.yaojiabuy.com`. In relay mode, port 443 is the snitun relay. It matches the TLS name and splices the bytes to the hub peer that already dialed out. |
| ROCK 5T hub | Terminates TLS on `127.0.0.1:8444`. Checks the forwarder secret and the lights-only token. Reads `hub/data/zigbee.db` during discovery. Sends Zigbee OnOff to the bulb through `/dev/ttyUSB0`. |

## How a bulb becomes an Alexa device

The IEEE address is already on the ROCK when the bulb joins the coordinator. zigpy stores it in `hub/data/zigbee.db` and loads it when the hub starts. Alexa does not have that address until discovery succeeds.

1. In the Alexa app, enable the Home AI skill and sign in with the hub owner account. The app opens `https://rock.link.yaojiabuy.com/alexa/oauth/authorize`. The hub checks the client id, the Amazon redirect URL, and the `state` value, then issues a code. Alexa exchanges that code at `/alexa/oauth/token`.
2. The hub token is a normal login JWT with `device_role` `alexa`, `scope` `lights`, and `can_unlock` false. Alexa keeps it and sends it inside later directives. The login API still only mints `phone` or `station` tokens, so a user cannot create an Alexa token by calling `/v1/auth/login`.
3. Alexa then sends `Alexa.Authorization` / `AcceptGrant` through Lambda to `POST /alexa`. The hub answers `AcceptGrant.Response`.
4. Say “Alexa, discover devices,” or tap the discovery step in the app. Alexa sends `Alexa.Discovery` / `Discover` through the same Lambda and Cloud Link path.
5. The hub walks the coordinator’s device table. It keeps one entry per Zigbee light (device types `0x0100`, `0x0101`, `0x0102`, `0x010C`, `0x010D`, `0x0210`, `0x0220`) that has the OnOff cluster. The scene remote is left out. A remote with OnOff on several endpoints would otherwise repeat one IEEE address, and Alexa drops the entire list when any `endpointId` is repeated.
6. Each entry uses the IEEE address as `endpointId`. The spoken name is the Zigbee model, or `Zigbee bulb` when the model is missing. Characters other than letters, numbers, spaces, and apostrophes are turned into spaces. If two bulbs share that name, the hub appends the last four hex digits of the IEEE address. The four Sengled `E11-G13` bulbs are therefore `E11 G13 0044`, `E11 G13 1a64`, `E11 G13 2a9a`, and `E11 G13 2e77`.
7. Alexa stores that list in the Amazon account. The app shows the bulbs under Devices → Lights. Until this step succeeds, the app has nothing to show.

The relay never sees the IEEE address. It only carries the encrypted connection.

## How “turn on” reaches the bulb

1. The Dot sends the sentence to Alexa cloud.
2. Alexa maps the stored name to one `endpointId` and invokes Lambda with `Alexa.PowerController` / `TurnOn` or `TurnOff`. The directive includes the lights-only token. Alexa stops waiting after about 8 seconds.
3. Lambda posts that JSON to `https://rock.link.yaojiabuy.com/alexa` with header `X-Home-Ai-Forwarder`. The function itself waits 7 seconds.
4. DNS for `rock.link.yaojiabuy.com` is `8.129.103.161`. The relay splices the TLS connection to the hub. TLS ends on the hub’s Let’s Encrypt certificate.
5. `POST /alexa` accepts the request when the forwarder header matches `HUB_ALEXA_FORWARD_SECRET`. A request without that header must instead carry a valid Alexa HTTPS signature. The token must still be a hub JWT with `scope` `lights` and `device_role` `alexa`.
6. The hub writes the Zigbee OnOff cluster for that IEEE address (`on` is `0x01`, `off` is `0x00`). An unlock directive is refused here and is not sent to the bolt. A lock directive is sent to the lock.

## Alarm, doors, and lock status

Discovery also returns three more kinds of endpoint:

| Spoken name | What Alexa can do |
|---|---|
| `Alarm` | “Alexa, arm Alarm” and “Alexa, disarm.” The hub has one armed state, reported as `ARMED_AWAY` or `DISARMED`. |
| `Door 1`, `Door 2`, … | “Alexa, is Door 1 open?” Open is `DETECTED`. Closed is `NOT_DETECTED`. A sensor that has not reported yet is unreachable until its magnet moves. |
| `Front door lock` | “Alexa, lock the front door lock” locks the bolt. “Alexa, is the front door lock locked?” reports `LOCKED` or `UNLOCKED`. “Alexa, unlock” is refused. Unlock stays on the hub API and still requires `confirm=true`. |

Say “Alexa, discover devices” again after this hub change so Amazon stores the new endpoints.
7. The hub returns an Alexa `Response` with `powerState` `ON` or `OFF`. Lambda returns that JSON unchanged. Alexa plays the Dot’s chime.

## Configure Cloud Link

Cloud Link has to be up before the skill can reach the house. Switching the public port is documented in [link/SWITCH.md](../link/SWITCH.md).

On the Aliyun server, relay mode owns public 443:

```bash
/opt/home-ai-link/link/switch-mode.sh relay
```

DNS for this trial:

| Host | Type | Value |
|---|---|---|
| `link` | A | `8.129.103.161` |
| `*.link` | A | `8.129.103.161` |

The wildcard does not answer the apex name `link.yaojiabuy.com`. The house name is `rock.link.yaojiabuy.com`.

The hub dials out. It does not need a port forward on the home router. In `/home/radxa/home-ai-security/hub.env`:

| Variable | Trial value |
|---|---|
| `HUB_LINK_URL` | `yaojiabuy.com:443` |
| `HUB_LINK_HOSTNAME` | `rock.link.yaojiabuy.com` |
| `HUB_LINK_FERNET_KEY` | same key as `LINK_FERNET_KEYS` in `/etc/home-ai-link.env` |
| `HUB_LINK_CERT` | `/home/radxa/home-ai-security/certs/link.pem` |
| `HUB_LINK_KEY` | `/home/radxa/home-ai-security/certs/link-key.pem` |

The certificate is Let’s Encrypt for `rock.link.yaojiabuy.com`. It is not the Tailscale certificate on port 8443. Do not print the Fernet key. The relay key file on Aliyun is mode 600.

The hub agent starts only when those three link variables are set and both certificate files exist. It retries the dial every 15 seconds. Health on the public name is `https://rock.link.yaojiabuy.com/health`.

TURN is not part of this feature. Login, discovery, and light control do not use it.

## Configure the hub for Alexa

Set these in `hub.env`. Do not commit the file and do not print the secrets.

| Variable | Trial value |
|---|---|
| `HUB_ALEXA_CLIENT_ID` | `home-ai-bb5ca9c5000f32d9` |
| `HUB_ALEXA_CLIENT_SECRET` | the skill’s account-linking secret |
| `HUB_ALEXA_FORWARD_SECRET` | shared with the Lambda variable `FORWARD_SECRET` |

Restart `home-ai-hub` after changing them. A restart clears in-memory door state until each sensor transmits again.

Code lives in `hub/alexa/` and `hub/api/alexa.py`. The forwarder source for Lambda is `link/alexa_forwarder/lambda_function.py`.

## Configure the Alexa skill

The developer console and the AWS console are separate sign-ins, even with the same email.

1. Open the Alexa developer console and create a Smart Home skill. This trial uses the name Home AI, English (US), provision your own, development stage. Leave any older skill alone.
2. Skill id: `amzn1.ask.skill.0e03cb87-aeb7-462a-b9d2-9e41ca1191c0`.
3. Payload version **v3**. The Smart Home endpoint page only accepts an AWS Lambda ARN. There is no HTTPS endpoint field. English (US) requires that function in **us-east-1** (N. Virginia).
4. Account linking, authorization code grant, HTTP Basic:

| Field | Value |
|---|---|
| Authorization URI | `https://rock.link.yaojiabuy.com/alexa/oauth/authorize` |
| Access Token URI | `https://rock.link.yaojiabuy.com/alexa/oauth/token` |
| Client ID | `home-ai-bb5ca9c5000f32d9` |
| Client secret | the same value as `HUB_ALEXA_CLIENT_SECRET` |
| Scope | `lights` |
| Domain | `rock.link.yaojiabuy.com` |
| Default token expiration | `28800` seconds |

Amazon’s redirect URLs for this skill are:

- `https://pitangui.amazon.com/api/skill/link/MXX6K0R1NUZQ`
- `https://layla.amazon.com/api/skill/link/MXX6K0R1NUZQ`
- `https://alexa.amazon.co.jp/api/skill/link/MXX6K0R1NUZQ`

The hub only accepts an `https` redirect on an Amazon host whose path starts with `/api/skill/link/`. Alexa’s `state` value can be longer than 512 characters; the hub allows up to 4096.

5. After the Lambda in the next section exists, paste its ARN into **Default endpoint** and into the **North America** box. Leave Europe and Far East empty. Save.

Build page: `https://developer.amazon.com/alexa/console/ask/build/prebuilts/config/amzn1.ask.skill.0e03cb87-aeb7-462a-b9d2-9e41ca1191c0/development/en_US/smartHome`

Account linking page: `https://developer.amazon.com/alexa/console/ask/amzn1.ask.skill.0e03cb87-aeb7-462a-b9d2-9e41ca1191c0/development/en_US/account-linking`

## Configure AWS Lambda

Use the N. Virginia console: `https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions`

1. Create a function named `home-ai-alexa`, runtime Python 3.12, architecture x86_64. Leave ARM64, VPC, Function URL, and custom execution role off. The default role that can write CloudWatch logs is enough. A function inside a VPC cannot reach the public hub.
2. Replace the sample code with `link/alexa_forwarder/lambda_function.py` and deploy. The sample that returns “Hello from Lambda” succeeds in CloudWatch and never calls the hub, so the Alexa app stays empty.
3. Environment variables:

| Key | Value |
|---|---|
| `HUB_URL` | `https://rock.link.yaojiabuy.com/alexa` |
| `FORWARD_SECRET` | the same value as `HUB_ALEXA_FORWARD_SECRET` |

4. General configuration: timeout **8 seconds**. Leave memory at 128 MB.
5. Add trigger **Alexa Smart Home**. Skill id `amzn1.ask.skill.0e03cb87-aeb7-462a-b9d2-9e41ca1191c0`, with skill id verification on.
6. Copy the function ARN `arn:aws:lambda:us-east-1:966103099162:function:home-ai-alexa` into the skill’s Default endpoint and North America endpoint, then save the skill.

## Try it

Use the same Amazon account as the developer console.

1. Alexa app → More → Skills & Games → Your Skills → Dev → Home AI → Enable.
2. Sign in with the hub owner account when the page `rock.link.yaojiabuy.com` opens.
3. Say “Alexa, discover devices.”
4. In the app, open Devices → Lights. Say “Alexa, turn on” plus the name shown there.

The Wi-Fi hints on Alexa’s “can’t connect” page do not apply. That page means the discovery reply never became a device list. Check the hub journal for `POST /alexa` and the Lambda log group `/aws/lambda/home-ai-alexa`. A real forwarder call appears in both places at the same minute. CloudWatch with no error, and no matching line on the hub, means the function returned without calling `HUB_URL`.
