#!/usr/bin/env bash
set -u

SERVICE=ge360-rilievi-backend.service
WG_SERVICE=wg-quick@wg0.service
FW_SERVICE=ge360-direct-bridge-firewall.service
HEALTH=http://127.0.0.1:9888/healthz

log(){ printf '[GE360 BOOT] %s\n' "$*"; }

# Never rotate or recreate persistent identity here.
# This script only verifies/restarts services using existing state.

systemctl is-enabled --quiet "$WG_SERVICE" 2>/dev/null || systemctl enable "$WG_SERVICE" >/dev/null 2>&1 || true
systemctl is-enabled --quiet "$FW_SERVICE" 2>/dev/null || systemctl enable "$FW_SERVICE" >/dev/null 2>&1 || true
systemctl is-enabled --quiet "$SERVICE" 2>/dev/null || systemctl enable "$SERVICE" >/dev/null 2>&1 || true

systemctl is-active --quiet "$WG_SERVICE" || systemctl restart "$WG_SERVICE" || true
systemctl is-active --quiet "$FW_SERVICE" || systemctl restart "$FW_SERVICE" || true
systemctl is-active --quiet "$SERVICE" || systemctl restart "$SERVICE" || true

for _ in 1 2 3 4 5; do
  if curl -fsS --max-time 3 "$HEALTH" >/dev/null 2>&1; then
    log "backend health OK"
    exit 0
  fi
  sleep 2
done

log "backend health failed after boot; preserving configuration and state"
systemctl --no-pager --full status "$SERVICE" || true
wg show wg0 || true
exit 0
