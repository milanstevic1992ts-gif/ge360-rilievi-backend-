#!/usr/bin/env bash
set -euo pipefail

WG_IFACE="${GE360_BRIDGE_INTERFACE:-wg0}"
WG_PORT="${GE360_BRIDGE_PORT:-51820}"
BACKEND_PORT="${GE360_PORT:-9888}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root."
  exit 1
fi
command -v nft >/dev/null 2>&1 || { echo "nft not installed"; exit 1; }

nft list table inet ge360_direct_bridge >/dev/null 2>&1 && nft delete table inet ge360_direct_bridge || true
nft -f - <<EOF
table inet ge360_direct_bridge {
  chain input {
    type filter hook input priority -20; policy accept;
    iifname "lo" tcp dport $BACKEND_PORT accept
    iifname "$WG_IFACE" tcp dport $BACKEND_PORT accept
    tcp dport $BACKEND_PORT drop
    udp dport $WG_PORT accept
  }
}
EOF
