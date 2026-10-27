# Port 443: phone relay or Yaojia site

Only one of these can listen on public port 443. The Yaojia nginx config stays on disk at `/etc/nginx/sites-enabled/restaurant`. Switching does not delete it.

On the server:

```bash
/opt/home-ai-link/link/switch-mode.sh relay
/opt/home-ai-link/link/switch-mode.sh yaojia
```

## Relay mode

`switch-mode.sh relay` disables nginx and binds the Cloud Link tunnel to `0.0.0.0:443`.

- A phone connects to `https://<home-id>.link.yaojiabuy.com`. The relay forwards those bytes to the hub. It does not decrypt them.
- The hub dials this machine on port 443 with its relay key. That connection is not HTTPS.
- `https://yaojiabuy.com` no longer serves the Yaojia site. The name still resolves to this machine.
- The backup and voice API stays on `127.0.0.1:8091`.

After a reboot, nginx stays off and the relay takes 443 again.

## Yaojia mode

`switch-mode.sh yaojia` moves the relay back to `127.0.0.1:4430` and enables nginx.

- `https://yaojiabuy.com`, `www.yaojiabuy.com`, and `api.yaojiabuy.com` are the Yaojia site again, including port 80.
- The relay process keeps running, but only on this machine. Phones and the hub cannot reach it until you switch back.
- Nginx config is the same file that was already there: `/etc/nginx/sites-enabled/restaurant`.

After a reboot, nginx takes 443 and the relay stays on port 4430.

## What neither mode changes

- DNS for `link.yaojiabuy.com` and `*.link.yaojiabuy.com` still points at this machine.
- The relay key stays in `/etc/home-ai-link.env`. The script does not print it.
- UDP 3478 and UDP 49160–49200 stay open for TURN. TURN is not what is listening on 443.
