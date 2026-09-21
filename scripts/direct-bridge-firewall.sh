#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
ENV_FILE="$CONFIG_DIR/bridge.env"
APPS_DIR="$CONFIG_DIR/apps.d"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root."
  exit 1
fi
command -v nft >/dev/null 2>&1 || { echo "nft not installed"; exit 1; }

read_env_value() {
  local file="$1" key="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$file"
}

WG_IFACE="wg0"
WG_PORT="51820"
if [[ -f "$ENV_FILE" ]]; then
  value="$(read_env_value "$ENV_FILE" GE360_BRIDGE_INTERFACE || true)"
  [[ -n "$value" ]] && WG_IFACE="$value"
  value="$(read_env_value "$ENV_FILE" GE360_BRIDGE_PORT || true)"
  [[ -n "$value" ]] && WG_PORT="$value"
fi

[[ "$WG_IFACE" =~ ^[A-Za-z0-9_=+.-]{1,15}$ ]] || { echo "Invalid WireGuard interface"; exit 1; }
[[ "$WG_PORT" =~ ^[0-9]+$ ]] && (( WG_PORT >= 1 && WG_PORT <= 65535 )) || { echo "Invalid WireGuard port"; exit 1; }

PORTS=()
if [[ -d "$APPS_DIR" ]]; then
  shopt -s nullglob
  for file in "$APPS_DIR"/*.env; do
    enabled="$(read_env_value "$file" APP_ENABLED || true)"
    [[ -z "$enabled" || "$enabled" =~ ^(1|true|yes|on)$ ]] || continue
    port="$(read_env_value "$file" APP_PORT || true)"
    [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || continue
    PORTS+=("$port")
  done
fi

# Backward compatibility: protect Rilievi even before apps.d is populated.
if (( ${#PORTS[@]} == 0 )); then
  PORTS+=("${GE360_PORT:-9888}")
fi

nft list table inet ge360_direct_bridge >/dev/null 2>&1 && nft delete table inet ge360_direct_bridge || true

{
  echo 'table inet ge360_direct_bridge {'
  echo '  chain input {'
  echo '    type filter hook input priority -20; policy accept;'
  echo "    udp dport $WG_PORT accept"
  for port in "${PORTS[@]}"; do
    echo "    iifname \"lo\" tcp dport $port accept"
    echo "    iifname \"$WG_IFACE\" tcp dport $port accept"
    echo "    tcp dport $port drop"
  done
  echo '  }'
  echo '}'
} | nft -f -

echo "GE360 Direct Bridge firewall loaded. Protected backend ports: ${PORTS[*]}"
