# TLS certificates

Place mkcert output here (gitignored):

- `hub.pem`
- `hub-key.pem`

If these files are missing, the hub generates a localhost self-signed pair for first boot. Android apps and Tailscale hostnames need a real mkcert CA — see [docs/setup.md](../docs/setup.md).
