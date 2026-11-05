# Alexa through Cloud Link and Home Assistant

Alexa can turn Zigbee lights on and off, arm and disarm the alarm, and lock the front door. It cannot unlock. Unlock is the Companion app, with the lock PIN. This is a private development skill for one house. It is not certified, and it is not in the skill store.

The spoken audio never reaches the house. The Echo sends it to Alexa cloud. What comes back is a Smart Home directive. Lambda posts that JSON to Home Assistant through Cloud Link. The Aliyun relay splices the TLS connection and does not decrypt it.

## Who does what

| Piece | Role |
|---|---|
| Echo | Microphone and speaker. It has no path to the bulb or the board. |
| Alexa cloud | Turns speech into a Smart Home directive and invokes Lambda. |
| AWS Lambda `home-ai-alexa` | Runs in us-east-1. Forwards the directive to Home Assistant with the account-linking token, or `HA_TOKEN` when the request has none. |
| Aliyun Cloud Link | `8.129.103.161`, public name `rock.link.yaojiabuy.com`. The board dials out. Caddy on `127.0.0.1:8444` presents the Let's Encrypt certificate and proxies to Home Assistant on port 8123. |
| Home Assistant | `POST /api/alexa/smart_home`. The `lock` domain is excluded. `script.lock_front_door` only calls `lock.lock`. |

Skill id: `amzn1.ask.skill.0e03cb87-aeb7-462a-b9d2-9e41ca1191c0`.

Lambda ARN: `arn:aws:lambda:us-east-1:966103099162:function:home-ai-alexa`.

## What Alexa can say

| Spoken name | Action |
|---|---|
| A light's name | Turn on or off. |
| `Alarm` | Arm or disarm `alarm_control_panel.alarm`. |
| A door sensor | Ask whether it is open. |
| `Front door lock` | Runs the lock script. There is no unlock command. `Front door bolt` reports the bolt. |

After lights, sensors, or the script change, say "Alexa, discover devices" again.

## Account linking

In the Alexa developer console, for this skill:

| Field | Value |
|---|---|
| Authorization URI | `https://rock.link.yaojiabuy.com/auth/authorize` |
| Access Token URI | `https://rock.link.yaojiabuy.com/auth/token` |
| Client ID | `alexa_client_id` in Home Assistant `secrets.yaml` |
| Client secret | `alexa_client_secret` in the same file |

`configuration.yaml` sets the Alexa client id and secret from those secrets, and the entity filter. Payload version is v3. The skill endpoint is the Lambda ARN in us-east-1, not an HTTPS URL.

Amazon's redirect URLs stay the skill's existing `/api/skill/link/` URLs.

## Lambda

Replace the function code with [link/alexa_forwarder/lambda_function.py](../link/alexa_forwarder/lambda_function.py).

| Key | Value |
|---|---|
| `HUB_URL` | `https://rock.link.yaojiabuy.com/api/alexa/smart_home` |
| `HA_TOKEN` | A Home Assistant long-lived access token |

Timeout 8 seconds. Trigger: Alexa Smart Home, skill id above, verification on. The function forwards `Authorization: Bearer` and does not send `X-Home-Ai-Forwarder`.

## Try it

1. Enable the skill and sign in as the Home Assistant user when `rock.link.yaojiabuy.com` opens.
2. Say "Alexa, discover devices."
3. Turn a light on. Arm and disarm the alarm. Lock the door with "Alexa, turn on Front door lock."
4. Confirm there is no unlock device.

CloudWatch log group: `/aws/lambda/home-ai-alexa`. A discovery that never becomes a device list means the function did not reach `HUB_URL` or Home Assistant rejected the token.
