#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.1.0}"
OUT="${2:-$PWD}"
NAME="GE360-Universal-Bridge-Kit-v$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

KIT="$TMP/$NAME"
mkdir -p   "$KIT/bridgekit"   "$KIT/scripts"   "$KIT/config"   "$KIT/systemd"   "$KIT/packaging/desktop"   "$KIT/docs"   "$KIT/frontend"

cp -a "$ROOT/backend/bridge/." "$KIT/bridgekit/"
cp "$ROOT/scripts/install-universal-bridge-core.sh" "$KIT/scripts/"
cp "$ROOT/scripts/register-bridge-app.sh" "$KIT/scripts/"
cp "$ROOT/scripts/direct-bridge-firewall.sh" "$KIT/scripts/"
cp "$ROOT/scripts/ge360-boot-verify.sh" "$KIT/scripts/"
cp "$ROOT/scripts/ge360-bridge-network-auto.sh" "$KIT/scripts/"
cp "$ROOT/scripts/ge360-bridge-wizard.sh" "$KIT/scripts/"
cp "$ROOT/scripts/ge360-bridge-terminal-launcher.sh" "$KIT/scripts/"
cp "$ROOT/scripts/install-bridge-desktop-launcher.sh" "$KIT/scripts/"
cp "$ROOT/scripts/export-frontend-bridge-kit.sh" "$KIT/scripts/"
cp "$ROOT/config/bridge.env.example" "$KIT/config/"
cp "$ROOT/packaging/deb/ge360-boot-verify.service" "$KIT/systemd/"
cp "$ROOT/packaging/desktop/ge360-universal-bridge.desktop" "$KIT/packaging/desktop/"
cp "$ROOT/docs/universal-direct-bridge.md" "$KIT/docs/"
cp "$ROOT/docs/guided-installation.md" "$KIT/docs/"
cp "$ROOT/docs/frontend-guided-connection.md" "$KIT/docs/"
cp "$ROOT/docs/direct-bridge.md" "$KIT/docs/rilievi-reference.md"
cp -a "$ROOT/frontend/android-sdk" "$KIT/frontend/android-sdk"

cat > "$KIT/README.md" <<EOF
# GE360 Universal Bridge Kit v$VERSION

Bridge WireGuard riutilizzabile per backend e frontend GE360.

## Installazione guidata

Dalla cartella del kit:

    sudo bash scripts/ge360-bridge-wizard.sh

Il wizard:
- installa/configura WireGuard;
- preserva chiavi e dispositivi esistenti;
- rileva IPv6/IPv4 pubblico;
- tenta UPnP UDP 51820 quando possibile;
- rileva CGNAT;
- configura firewall e reboot persistence;
- registra backend;
- può generare lo ZIP frontend per l'app.

Dopo la prima installazione compare anche:

    GE360 Universal Bridge

nel menu applicazioni. Apre il terminale e avvia il wizard.

## Solo core

    sudo bash scripts/install-universal-bridge-core.sh

## Registrazione app

    sudo APP_ID=myapp \
      APP_NAME="GE360 My App" \
      APP_PORT=9890 \
      APP_SERVICE=myapp.service \
      APP_HEALTH_URL=http://127.0.0.1:9890/healthz \
      /usr/local/sbin/ge360-bridge-register-app

## Frontend

    sudo ge360-bridge-export-frontend myapp

Il pacchetto contiene l'Android SDK GE360 Bridge basato sulla libreria ufficiale WireGuard Android.

## Persistenza

Non cancellare durante aggiornamenti/reinstallazioni:

    /etc/ge360/direct-bridge
    /var/lib/ge360/direct-bridge

Il kit non promette di creare un IP pubblico quando l'operatore usa CGNAT senza IPv6 raggiungibile.
In quel caso segnala BLOCKED_CGNAT e indica il requisito di rete mancante.
EOF

cat > "$KIT/requirements.txt" <<'EOF'
qrcode>=7.4,<9
pydantic>=2.8
EOF

find "$KIT/scripts" -type f -name '*.sh' -exec chmod 0755 {} +

mkdir -p "$OUT"
if command -v zip >/dev/null 2>&1; then
  (cd "$TMP" && zip -qr "$OUT/$NAME.zip" "$NAME")
  echo "$OUT/$NAME.zip"
else
  tar -C "$TMP" -czf "$OUT/$NAME.tar.gz" "$NAME"
  echo "$OUT/$NAME.tar.gz"
fi
