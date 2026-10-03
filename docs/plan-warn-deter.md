# Future plan: warn or deter

Siren, LED, and the Zigbee light run for an armed person at the door. A spoken warning is still not built.

## What exists

A confirmed person on the doorbell, while the hub is armed, saves a snapshot, sets the alarm flag, and sends `person_at_door` to the phone. The driveway writes its own event and does not set the door alarm. The alarm clears when the person leaves.

Talk plays a live voice on the doorbell speaker only after someone opens a Talk session. That spoken warning is not triggered by person detection. An armed person at the door turns on the one Zigbee bulb named by `HUB_DOOR_LIGHT`, and that bulb goes off when the person leaves. The driveway does not change the lights.

## What this plan adds

After a confirmed person event, the hub may act on its own:

- Speak a short warning on the doorbell speaker.
- Turn on a light.
- A siren and LED on the Elegoo Mega 2560. That board has no Wi-Fi. It is a USB serial device on the Dell PC (`COM6`). The sketch is `firmware/elegoo-mega/elegoo-mega.ino` (LED on pin 8, buzzer on pin 9, 4 second burst). `python -m hub.elegoo_alert` on that PC sends one `ON` for a new person at the door while armed, ignores the driveway, and sends `OFF` on disarm. It does not unlock.

The phone notice stays. These actions are in addition to the notice, not a replacement.

## Limits

- No automatic unlock. Unlock stays on the HTTPS lock adapter and still requires `confirm=true`.
- The driveway does not set the door alarm and does not speak on the doorbell.
- Act only while armed, and only after the same confirmed-person streak used for the alert.
- One action per visit, then the existing cooldown. Do not repeat the warning on every frame.
- Keep it local. No cloud service decides or plays the warning.
