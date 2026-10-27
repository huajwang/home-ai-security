#!/bin/bash
# Switch public port 443 between the phone relay and the Yaojia site.
# The nginx site file is not deleted. See link/SWITCH.md.

set -euo pipefail

ENV_FILE=/etc/home-ai-link.env
MODE=${1:-}

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set_kv() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

case "$MODE" in
  relay)
    systemctl disable --now nginx
    set_kv LINK_SNI_HOST 0.0.0.0
    set_kv LINK_SNI_PORT 443
    systemctl enable --now home-ai-link
    systemctl restart home-ai-link
    ;;
  yaojia)
    set_kv LINK_SNI_HOST 127.0.0.1
    set_kv LINK_SNI_PORT 4430
    systemctl restart home-ai-link
    systemctl enable --now nginx
    ;;
  *)
    echo "usage: $0 relay|yaojia" >&2
    exit 2
    ;;
esac

chmod 600 "$ENV_FILE"
echo "mode=$MODE"
systemctl is-active home-ai-link || true
systemctl is-active nginx || true
ss -lnt | awk '/:443 |:4430|:8091 /'
