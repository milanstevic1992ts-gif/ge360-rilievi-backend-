#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
APPS_DIR="$CONFIG_DIR/apps.d"

APP_ID="${APP_ID:-}"
APP_NAME="${APP_NAME:-$APP_ID}"
APP_PORT="${APP_PORT:-}"
APP_SERVICE="${APP_SERVICE:-}"
APP_HEALTH_URL="${APP_HEALTH_URL:-}"
APP_ENABLED="${APP_ENABLED:-true}"

if [[ $EUID -ne 0 ]]; then
  echo "Use sudo/root."
  exit 1
fi

[[ "$APP_ID" =~ ^[a-z0-9][a-z0-9_-]{0,31}$ ]] || {
  echo "APP_ID invalid. Use lowercase letters, numbers, _ or -."
  exit 1
}
[[ "$APP_PORT" =~ ^[0-9]+$ ]] && (( APP_PORT >= 1 && APP_PORT <= 65535 )) || {
  echo "APP_PORT invalid."
  exit 1
}
[[ -z "$APP_SERVICE" || "$APP_SERVICE" =~ ^[A-Za-z0-9_.@:-]+$ ]] || {
  echo "APP_SERVICE invalid."
  exit 1
}

install -d -m 0750 "$APPS_DIR"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

cat > "$tmp" <<EOF
APP_ID=$APP_ID
APP_NAME=$APP_NAME
APP_PORT=$APP_PORT
APP_SERVICE=$APP_SERVICE
APP_HEALTH_URL=$APP_HEALTH_URL
APP_ENABLED=$APP_ENABLED
EOF

install -m 0640 "$tmp" "$APPS_DIR/$APP_ID.env"

systemctl restart ge360-direct-bridge-firewall.service || true
systemctl restart ge360-boot-verify.service || true

echo "Registered GE360 Bridge app: $APP_ID -> TCP $APP_PORT"
