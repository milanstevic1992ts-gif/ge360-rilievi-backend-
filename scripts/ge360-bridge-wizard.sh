#!/usr/bin/env bash
set -euo pipefail

SELF="$(readlink -f "$0")"
ROOT="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd || true)"
AUTO=false
[[ "${1:-}" == "--auto" ]] && AUTO=true

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$SELF" "$@"
fi

find_script() {
  local name="$1" installed="$2"
  if [[ -n "$ROOT" && -x "$ROOT/scripts/$name" ]]; then
    printf '%s\n' "$ROOT/scripts/$name"
  elif [[ -x "$installed" ]]; then
    printf '%s\n' "$installed"
  else
    echo "Script mancante: $name" >&2
    exit 1
  fi
}

CORE="$(find_script install-universal-bridge-core.sh /usr/local/sbin/ge360-bridge-core-install)"
NET="$(find_script ge360-bridge-network-auto.sh /usr/local/sbin/ge360-bridge-network-auto)"
REGISTER="$(find_script register-bridge-app.sh /usr/local/sbin/ge360-bridge-register-app)"

clear || true
cat <<'EOF'
============================================================
              GE360 UNIVERSAL BRIDGE SETUP
============================================================
Questo wizard prepara automaticamente:
  • WireGuard e identità persistente
  • rete VPN GE360
  • IPv4/IPv6 pubblico quando disponibile
  • UPnP port mapping quando possibile
  • firewall e servizi al reboot
  • registrazione dei backend
  • base per pairing QR frontend
============================================================
EOF

echo
echo "[1/5] Installazione/aggiornamento core..."
bash "$CORE"

echo
echo "[2/5] Configurazione automatica rete pubblica..."
bash "$NET" --apply || true

echo
echo "[3/5] Registrazione backend..."
if $AUTO; then
  if [[ -n "${APP_ID:-}" && -n "${APP_PORT:-}" ]]; then
    APP_ID="$APP_ID" APP_NAME="${APP_NAME:-$APP_ID}" APP_PORT="$APP_PORT"     APP_SERVICE="${APP_SERVICE:-}" APP_HEALTH_URL="${APP_HEALTH_URL:-}"     bash "$REGISTER"
  else
    echo "Modalità auto: nessun APP_ID/APP_PORT fornito, salto registrazione."
  fi
else
  read -r -p "Vuoi registrare ora un backend? [S/n] " answer
  answer="${answer:-S}"
  if [[ "$answer" =~ ^[SsYy]$ ]]; then
    read -r -p "ID app (es. rilievi): " app_id
    read -r -p "Nome app [$app_id]: " app_name
    app_name="${app_name:-$app_id}"
    read -r -p "Porta backend (es. 9888): " app_port
    read -r -p "Servizio systemd (opzionale): " app_service
    read -r -p "Health URL [http://127.0.0.1:$app_port/healthz]: " app_health
    app_health="${app_health:-http://127.0.0.1:$app_port/healthz}"
    APP_ID="$app_id" APP_NAME="$app_name" APP_PORT="$app_port"     APP_SERVICE="$app_service" APP_HEALTH_URL="$app_health"     bash "$REGISTER"
  fi
fi

echo
echo "[4/5] Avvio e persistenza..."
systemctl daemon-reload
systemctl restart ge360-direct-bridge-firewall.service || true
systemctl restart wg-quick@wg0.service || true
systemctl restart ge360-boot-verify.service || true

echo
echo "[5/5] Verifica finale..."
echo "-- WireGuard --"
wg show wg0 || true
echo
echo "-- Endpoint pubblico --"
cat /var/lib/ge360/direct-bridge/state/network.json 2>/dev/null || true
echo
echo "-- App registrate --"
for f in /etc/ge360/direct-bridge/apps.d/*.env; do
  [[ -e "$f" ]] || continue
  echo "### $(basename "$f")"
  cat "$f"
done

echo
echo "============================================================"
echo "Setup GE360 Universal Bridge completato."
echo "Per il frontend: scansiona il QR generato dal backend GE360."
echo "Se lo stato rete mostra BLOCKED_CGNAT, serve IPv6 raggiungibile"
echo "o un IPv4 pubblico dell'operatore: il software non può crearne uno."
echo "============================================================"
