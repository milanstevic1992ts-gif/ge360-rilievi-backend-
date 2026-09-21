#!/usr/bin/env bash
set -euo pipefail

APP_ID="${1:-}"
OUT_DIR="${2:-}"
CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
APPS_DIR="$CONFIG_DIR/apps.d"
INSTALL_ROOT="${GE360_BRIDGE_INSTALL_ROOT:-/opt/ge360/universal-bridge-kit}"

if [[ -z "$APP_ID" ]]; then
  echo "Uso: ge360-bridge-export-frontend APP_ID [CARTELLA_OUTPUT]"
  echo
  echo "App disponibili:"
  for f in "$APPS_DIR"/*.env; do
    [[ -e "$f" ]] || continue
    awk -F= '/^APP_ID=/{print "  - "$2}' "$f"
  done
  exit 1
fi

PROFILE="$APPS_DIR/$APP_ID.env"
[[ -f "$PROFILE" ]] || { echo "App non registrata: $APP_ID"; exit 1; }

read_env_value() {
  local file="$1" key="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$file"
}

APP_NAME="$(read_env_value "$PROFILE" APP_NAME || true)"
APP_PORT="$(read_env_value "$PROFILE" APP_PORT || true)"
SERVER_IP="$(read_env_value "$CONFIG_DIR/bridge.env" GE360_BRIDGE_SERVER_IP || true)"
SERVER_IP="${SERVER_IP:-10.88.0.1}"

if [[ -z "$OUT_DIR" ]]; then
  owner="${SUDO_USER:-${USER:-root}}"
  home="$(getent passwd "$owner" | cut -d: -f6)"
  [[ -n "$home" ]] || home="/tmp"
  if [[ -d "$home/Scaricati" ]]; then
    OUT_DIR="$home/Scaricati"
  elif [[ -d "$home/Downloads" ]]; then
    OUT_DIR="$home/Downloads"
  else
    OUT_DIR="$home"
  fi
fi

SOURCE_SDK=""
for candidate in   "$INSTALL_ROOT/frontend/android-sdk"   "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/frontend/android-sdk"; do
  if [[ -d "$candidate" ]]; then SOURCE_SDK="$candidate"; break; fi
done
[[ -n "$SOURCE_SDK" ]] || { echo "Android SDK template non trovato."; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
NAME="GE360-Frontend-Bridge-$APP_ID"
KIT="$tmp/$NAME"
mkdir -p "$KIT"
cp -a "$SOURCE_SDK" "$KIT/android-sdk"

python3 - "$KIT/ge360-bridge-profile.json" "$APP_ID" "$APP_NAME" "$APP_PORT" "$SERVER_IP" <<'PY'
from pathlib import Path
import json,sys
path=Path(sys.argv[1])
app_id,name,port,server_ip=sys.argv[2:]
data={
 "format":"GE360_FRONTEND_BRIDGE_PROFILE_V1",
 "app_id":app_id,
 "app_name":name or app_id,
 "backend_url":f"http://{server_ip}:{int(port)}",
 "health_url":f"http://{server_ip}:{int(port)}/api/v1/health",
 "pairing_qr_format":"GE360_DIRECT_BRIDGE_V1",
 "route_priority":["LAN","GE360_BRIDGE","OFFLINE"],
 "wireguard_network":"10.88.0.0/24",
}
path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
PY

cat > "$KIT/README.txt" <<EOF
GE360 FRONTEND BRIDGE KIT
=========================
App: $APP_NAME ($APP_ID)
Backend via Bridge: http://$SERVER_IP:$APP_PORT

1. Integra android-sdk/ nel frontend Android.
2. Aggiungi la dipendenza WireGuard indicata nel README del modulo.
3. Crea la schermata "Collega server GE360".
4. Passa il testo del QR a Ge360BridgeClient.importPairing().
5. Richiedi il consenso VPN Android se prepareVpnPermission() restituisce un Intent.
6. Dopo il consenso chiama connectAndVerify().
7. Usa Ge360EndpointRouter per LAN -> Bridge -> offline.

Il QR reale contiene credenziali per-device e viene generato dal backend.
Non inserire mai la master API key nel frontend.
EOF

mkdir -p "$OUT_DIR"
ARCHIVE="$OUT_DIR/$NAME.zip"
if command -v zip >/dev/null 2>&1; then
  (cd "$tmp" && zip -qr "$ARCHIVE" "$NAME")
else
  ARCHIVE="$OUT_DIR/$NAME.tar.gz"
  tar -C "$tmp" -czf "$ARCHIVE" "$NAME"
fi

owner="${SUDO_USER:-}"
if [[ -n "$owner" && "$owner" != "root" ]]; then
  chown "$owner":"$(id -gn "$owner")" "$ARCHIVE" || true
fi

echo "$ARCHIVE"
