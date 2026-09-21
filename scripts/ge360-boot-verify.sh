#!/usr/bin/env bash
set -u

CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
ENV_FILE="$CONFIG_DIR/bridge.env"
APPS_DIR="$CONFIG_DIR/apps.d"
FW_SERVICE=ge360-direct-bridge-firewall.service

read_env_value() {
  local file="$1" key="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$file"
}

WG_IFACE="wg0"
if [[ -f "$ENV_FILE" ]]; then
  value="$(read_env_value "$ENV_FILE" GE360_BRIDGE_INTERFACE || true)"
  [[ -n "$value" ]] && WG_IFACE="$value"
fi
WG_SERVICE="wg-quick@${WG_IFACE}.service"

log(){ printf '[GE360 BRIDGE BOOT] %s\n' "$*"; }

# Never rotate or recreate persistent identity here.
# This script only verifies/restarts services using existing state.
systemctl is-enabled --quiet "$WG_SERVICE" 2>/dev/null || systemctl enable "$WG_SERVICE" >/dev/null 2>&1 || true
systemctl is-enabled --quiet "$FW_SERVICE" 2>/dev/null || systemctl enable "$FW_SERVICE" >/dev/null 2>&1 || true
systemctl is-active --quiet "$WG_SERVICE" || systemctl restart "$WG_SERVICE" || true
systemctl is-active --quiet "$FW_SERVICE" || systemctl restart "$FW_SERVICE" || true

found_apps=false
if [[ -d "$APPS_DIR" ]]; then
  shopt -s nullglob
  for file in "$APPS_DIR"/*.env; do
    enabled="$(read_env_value "$file" APP_ENABLED || true)"
    [[ -z "$enabled" || "$enabled" =~ ^(1|true|yes|on)$ ]] || continue
    found_apps=true

    app_id="$(read_env_value "$file" APP_ID || true)"
    service="$(read_env_value "$file" APP_SERVICE || true)"
    health="$(read_env_value "$file" APP_HEALTH_URL || true)"

    if [[ -n "$service" ]]; then
      systemctl is-enabled --quiet "$service" 2>/dev/null || systemctl enable "$service" >/dev/null 2>&1 || true
      systemctl is-active --quiet "$service" || systemctl restart "$service" || true
    fi

    if [[ -n "$health" ]]; then
      ok=false
      for _ in 1 2 3 4 5; do
        if curl -fsS --max-time 3 "$health" >/dev/null 2>&1; then
          ok=true
          break
        fi
        sleep 2
      done
      if $ok; then
        log "${app_id:-app} health OK"
      else
        log "${app_id:-app} health failed; preserving Bridge identity and state"
        [[ -n "$service" ]] && systemctl --no-pager --full status "$service" || true
      fi
    fi
  done
fi

# Compatibility fallback for installations created before apps.d.
if ! $found_apps; then
  SERVICE=ge360-rilievi-backend.service
  HEALTH=http://127.0.0.1:9888/healthz
  systemctl is-enabled --quiet "$SERVICE" 2>/dev/null || systemctl enable "$SERVICE" >/dev/null 2>&1 || true
  systemctl is-active --quiet "$SERVICE" || systemctl restart "$SERVICE" || true
  curl -fsS --max-time 3 "$HEALTH" >/dev/null 2>&1 && log "rilievi health OK" || log "rilievi health failed; state preserved"
fi

wg show "$WG_IFACE" || true
exit 0
