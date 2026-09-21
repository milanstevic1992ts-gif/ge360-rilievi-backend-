#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/ge360/ge360-rilievi-backend
BRIDGE_ENV=/etc/ge360/direct-bridge/bridge.env

if [[ $EUID -ne 0 ]]; then
  echo "Usa sudo: sudo bash $0"
  exit 1
fi

echo "== GE360 Linux recovery =="

if [[ -x "$APP_DIR/.venv/bin/pip" ]]; then
  "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check \
    "numpy>=2.2,<2.4" "scipy>=1.15,<1.17"
fi

if [[ -f "$BRIDGE_ENV" ]]; then
  sed -i 's/^GE360_BRIDGE_AUTO_PORT_MAPPING=.*/GE360_BRIDGE_AUTO_PORT_MAPPING=false/' "$BRIDGE_ENV"
fi

systemctl daemon-reload || true
systemctl restart ge360-direct-bridge-firewall.service || true
systemctl restart wg-quick@wg0.service || true
systemctl reset-failed ge360-rilievi-backend.service || true
systemctl restart ge360-rilievi-backend.service || true

echo
systemctl --no-pager --full status ge360-rilievi-backend.service || true
echo
wg show wg0 || true
echo
curl -fsS --max-time 3 http://127.0.0.1:9888/healthz || true
echo
