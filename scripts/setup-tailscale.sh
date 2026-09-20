#!/usr/bin/env bash
set -euo pipefail

PORT="${GE360_PORT:-8796}"
DATA_DIR="${GE360_DATA_DIR:-/opt/ge360/data/rilievi}"
KEY_FILE="${GE360_API_KEY_FILE:-${DATA_DIR}/.api-key}"
SERVICE_USER="${GE360_SERVICE_USER:-jarvis}"

if [[ $EUID -ne 0 ]]; then
  echo "Esegui con sudo: sudo bash scripts/setup-tailscale.sh"
  exit 1
fi

if ! command -v tailscale >/dev/null 2>&1; then
  echo "[ERRORE] Tailscale non è installato."
  echo "Installa Tailscale, esegui 'sudo tailscale up', poi rilancia questo script."
  exit 1
fi

STATE="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState","UNKNOWN"))')"
if [[ "$STATE" != "Running" ]]; then
  echo "[ERRORE] Tailscale non risulta connesso (BackendState=$STATE)."
  echo "Esegui: sudo tailscale up"
  exit 1
fi

mkdir -p "$DATA_DIR"
if [[ ! -s "$KEY_FILE" ]]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    chown "$SERVICE_USER:$SERVICE_USER" "$KEY_FILE"
  fi
  echo "[OK] Nuova API key GE360 generata."
else
  echo "[OK] API key GE360 già presente: non viene ruotata."
fi

echo "[INFO] Configuro Tailscale Serve -> http://127.0.0.1:${PORT}"
tailscale serve --bg --yes "http://127.0.0.1:${PORT}"

DNS="$(tailscale status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(((d.get("Self") or {}).get("DNSName") or "").rstrip("."))')"
KEY="$(tr -d '\r\n' < "$KEY_FILE")"

echo
echo "============================================================"
echo " GE360 RILIEVI · CONFIGURAZIONE FRONTEND"
echo "============================================================"
if [[ -n "$DNS" ]]; then
  echo "Backend URL : https://${DNS}/api/v1"
else
  echo "Backend URL : controlla 'tailscale serve status'"
fi
echo "API key     : $KEY"
echo
echo "Pagina setup locale:"
echo "http://127.0.0.1:${PORT}/setup/"
echo "============================================================"
echo
echo "La API key è un segreto: non committarla e non condividerla pubblicamente."
