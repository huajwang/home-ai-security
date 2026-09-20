# Hub API v1

All control routes are HTTPS. Send `Authorization: Bearer <access_token>` unless noted.

Errors: `{ "code": "unauthorized", "message": "..." }` with HTTP 401 / 403 / 409 / 429.

## Auth / devices

### `POST /v1/auth/login` (no bearer)

```json
{
  "username": "owner",
  "password": "changeme",
  "device_name": "Pixel 8",
  "device_role": "phone"
}
```

`device_role` is `phone` or `station`. Response includes `access_token`, `refresh_token`, `user`, `home`, `device`.

### `POST /v1/auth/refresh`

```json
{ "refresh_token": "..." }
```

Rotates tokens.

### `POST /v1/auth/logout`

Revokes refresh tokens for this paired device.

### `GET /v1/me`

Current user, device, and home.

### `GET /v1/devices` / `DELETE /v1/devices/{id}`

Owner only.

## System

### `GET /v1/system`

```json
{
  "armed": false,
  "alarm_active": false,
  "vision": { "fps": 12.4, "running": true, "error": null, "last_person_at": null, "last_confidence": 0 },
  "lock": { "state": "locked", "updated_at": "...", "adapter": "stub" },
  "hub_time": "2026-09-10T00:00:00+00:00"
}
```

### `POST /v1/system/arm` / `POST /v1/system/disarm`

## Events

### `GET /v1/events?since=&limit=`

List `{ id, ts, label, confidence, snapshot_url }`.

### `GET /v1/events/{id}`

### `GET /v1/events/{id}/snapshot`

JPEG of the annotated doorway frame.

### `GET /v1/stream/events` (WebSocket)

Query `?access_token=` or `Authorization` header.

Messages:

- `{ "type": "person_at_door", "event": { ... } }`
- `{ "type": "alarm_cleared" }`
- `{ "type": "lock_changed", "state": "unlocked", "actor": "owner", "action": "unlock" }`
- `{ "type": "armed_changed", "armed": true, "actor": "owner" }`

## Lock (control plane only)

Never send unlock over WebRTC.

### `GET /v1/lock`

### `POST /v1/lock/lock`

### `POST /v1/lock/unlock`

```json
{ "confirm": true, "reason": "app" }
```

`confirm` must be `true`. 409 if already unlocked. 403 if the user cannot unlock. 429 if rate limited.

### `GET /v1/lock/audit`

## WebRTC signaling

Media is DTLS-SRTP. The hub is the door peer (PC camera + mic + speakers).

1. `POST /v1/calls` → `{ "call_id": "..." }`
2. Client creates an SDP offer (recv video, send/recv audio)
3. `POST /v1/calls/{id}/offer` `{ "sdp": "...", "type": "offer" }` → hub answer
4. Optional trickle: `POST /v1/calls/{id}/ice`
5. `DELETE /v1/calls/{id}` hang up
6. `POST /v1/calls/{id}/photo` — save a JPEG of the live doorway frame (`label: photo`)
7. `POST /v1/calls/{id}/clip/start` / `POST /v1/calls/{id}/clip/stop` — record a short MP4 (max 60s)

`GET /v1/events/{id}/clip` returns the MP4 when the event has a clip.

`POST /v1/calls/{id}/answer` exists if a future client wants the hub to offer.

## Health / dev

- `GET /health` — liveness, no auth
- `GET /dev/call` — browser probe only, not a product client
