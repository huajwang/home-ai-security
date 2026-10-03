# Future plan: warn or deter

Not built. Do not start this until it is asked for.

## What exists

A confirmed person on the doorbell, while the hub is armed, saves a snapshot, sets the alarm flag, and sends `person_at_door` to the phone. The driveway writes its own event and does not set the door alarm. The alarm clears when the person leaves.

Talk plays a live voice on the doorbell speaker only after someone opens a Talk session. Zigbee lights change only when a light command is sent. Neither is triggered by person detection.

## What this plan adds

After a confirmed person event, the hub may act on its own:

- Speak a short warning on the doorbell speaker.
- Turn on a light.
- A siren or other deterrent only if a device for that is added later.

The phone notice stays. These actions are in addition to the notice, not a replacement.

## Limits

- No automatic unlock. Unlock stays on the HTTPS lock adapter and still requires `confirm=true`.
- The driveway does not set the door alarm and does not speak on the doorbell.
- Act only while armed, and only after the same confirmed-person streak used for the alert.
- One action per visit, then the existing cooldown. Do not repeat the warning on every frame.
- Keep it local. No cloud service decides or plays the warning.
