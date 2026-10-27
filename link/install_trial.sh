#!/bin/bash
# Install the Cloud Link relay on the Ubuntu trial server.
# Does not reload nginx and does not stop the Yaojia site.
# Run on the server, from a checkout of this repo:
#   sudo bash link/install_trial.sh
#
# Before phones can use it:
#   1. DNS A record:    link.yaojiabuy.com      -> this machine
#   2. DNS A record:    *.link.yaojiabuy.com   -> this machine
#   3. Put LINK_FERNET_KEYS in /etc/home-ai-link.env
#      (the same value as HUB_LINK_FERNET_KEY on the hub)
#   4. Issue a certificate for each house with:
#        python -m hub.cloudlink.dns01
#      after ALIYUN_ACCESS_KEY_ID and ALIYUN_ACCESS_KEY_SECRET are set,
#      then follow certbot_args() in that module.
#   5. Only then include link/nginx-stream.conf. Public 443 is already
#      serving yaojiabuy.com, so the stream block has to sit in front of
#      that site. Do this by hand and run nginx -t first.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
install -d /opt/home-ai-link /var/lib/home-ai-link/backups
rm -rf /opt/home-ai-link/link
cp -a "$ROOT/link" /opt/home-ai-link/link
python3 -m venv /opt/home-ai-link/.venv
/opt/home-ai-link/.venv/bin/pip install "fastapi>=0.115.0" "uvicorn>=0.32.0" "snitun>=0.42.0" "cryptography>=42.0.0" "pydantic>=2"
touch /opt/home-ai-link/link/__init__.py
install -m 0644 "$ROOT/link/home-ai-link.service" /etc/systemd/system/home-ai-link.service
if [[ ! -f /etc/home-ai-link.env ]]; then
  umask 077
  echo "LINK_REGION=cn" > /etc/home-ai-link.env
  echo "LINK_FERNET_KEYS=" >> /etc/home-ai-link.env
  echo "Write the hub's HUB_LINK_FERNET_KEY into /etc/home-ai-link.env before starting."
fi
systemctl daemon-reload
systemctl enable home-ai-link
echo "Relay files are in place. systemctl start home-ai-link after the fernet key is set."
echo "coturn config is link/coturn.conf. Open UDP 3478 and UDP 49160-49200 before expecting video."
