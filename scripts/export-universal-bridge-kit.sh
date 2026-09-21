#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.0.0}"
OUT="${2:-$PWD}"
NAME="GE360-Universal-Bridge-Kit-v$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

KIT="$TMP/$NAME"
mkdir -p "$KIT/bridgekit" "$KIT/scripts" "$KIT/config" "$KIT/systemd" "$KIT/docs"

cp -a "$ROOT/backend/bridge/." "$KIT/bridgekit/"
cp "$ROOT/scripts/install-universal-bridge-core.sh" "$KIT/scripts/"
cp "$ROOT/scripts/register-bridge-app.sh" "$KIT/scripts/"
cp "$ROOT/scripts/direct-bridge-firewall.sh" "$KIT/scripts/"
cp "$ROOT/scripts/ge360-boot-verify.sh" "$KIT/scripts/"
cp "$ROOT/config/bridge.env.example" "$KIT/config/"
cp "$ROOT/packaging/deb/ge360-boot-verify.service" "$KIT/systemd/"
cp "$ROOT/docs/universal-direct-bridge.md" "$KIT/docs/"
cp "$ROOT/docs/direct-bridge.md" "$KIT/docs/rilievi-reference.md"

cat > "$KIT/README.md" <<EOF
# GE360 Universal Bridge Kit v$VERSION

Estratto dalla repository GE360 Rilievi.

Contiene:
- core Python Bridge riutilizzabile;
- installer Debian/systemd;
- firewall multi-app;
- verifica automatica dopo reboot;
- registrazione backend tramite apps.d;
- configurazione persistente WireGuard.

Installazione core:
  sudo bash scripts/install-universal-bridge-core.sh

Registrazione di un'app:
  sudo APP_ID=myapp APP_PORT=9890 APP_SERVICE=myapp.service \
    APP_HEALTH_URL=http://127.0.0.1:9890/healthz \
    /usr/local/sbin/ge360-bridge-register-app

Il kit preserva /etc/ge360/direct-bridge e /var/lib/ge360/direct-bridge.
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
