#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${GE360_APP_DIR:-/opt/ge360/ge360-rilievi-backend}"
DATA_DIR="${GE360_DATA_DIR:-/opt/ge360/data/rilievi}"
DOCUMENTS_DIR="${GE360_DOCUMENTS_DIR:-/opt/ge360/Documenti/Rilievi}"
BACKUP_DIR="${GE360_CONFIG_BACKUP_DIR:-/opt/ge360/Backup/Configurazione}"
SERVICE_NAME="ge360-rilievi-backend.service"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo/root: sudo bash scripts/install-debian.sh"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

mkdir -p "$APP_DIR" "$DATA_DIR" "$DOCUMENTS_DIR" "$BACKUP_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$PYTHON_BIN" "$SCRIPT_DIR/scripts/verify-control-assets.py" "$SCRIPT_DIR"
if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
  rsync -a --delete --exclude '.git' --exclude '.env' --exclude '.venv' "$SCRIPT_DIR/" "$APP_DIR/"
fi

cd "$APP_DIR"
"$PYTHON_BIN" "$APP_DIR/scripts/verify-control-assets.py" "$APP_DIR"
if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created $APP_DIR/.env."
else
  echo "Existing .env preserved."
fi

SERVICE_USER="${GE360_SERVICE_USER:-jarvis}"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  SERVICE_USER="${SUDO_USER:-root}"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$DOCUMENTS_DIR" || true

KEY_FILE="$DATA_DIR/.api-key"
if [[ ! -s "$KEY_FILE" ]] && ! grep -Eq '^GE360_API_KEY=.{16,}$' .env; then
  "$PYTHON_BIN" - <<PY
from pathlib import Path
import secrets, os
p=Path("$KEY_FILE")
p.parent.mkdir(parents=True, exist_ok=True)
tmp=p.with_name(p.name+".tmp")
tmp.write_text(secrets.token_urlsafe(48)+"\n", encoding="utf-8")
os.chmod(tmp,0o600)
os.replace(tmp,p)
PY
  chown "$SERVICE_USER:$SERVICE_USER" "$KEY_FILE" || true
  chmod 600 "$KEY_FILE"
  echo "Generated mandatory GE360 API key in $KEY_FILE"
fi
chmod +x "$APP_DIR/scripts/preflight.sh"

install -m 0755 "$APP_DIR/scripts/ge360-config-backup.sh" /usr/local/sbin/ge360-config-backup
install -m 0755 "$APP_DIR/scripts/ge360-config-restore.sh" /usr/local/sbin/ge360-config-restore
install -m 0755 "$APP_DIR/scripts/update-debian.sh" /usr/local/sbin/ge360-rilievi-update
install -m 0644 "$APP_DIR/packaging/deb/ge360-config-backup.service" /etc/systemd/system/ge360-config-backup.service
install -m 0644 "$APP_DIR/packaging/deb/ge360-config-backup.timer" /etc/systemd/system/ge360-config-backup.timer

mkdir -p /etc/systemd/system/$SERVICE_NAME.d
cat > /etc/systemd/system/$SERVICE_NAME.d/20-documents-archive.conf <<EOF
[Service]
ReadWritePaths=$DOCUMENTS_DIR
EOF

TARGET_SERVICE="/etc/systemd/system/$SERVICE_NAME"
if [[ -e "$TARGET_SERVICE" ]]; then
  echo "Existing $TARGET_SERVICE preserved. Review deploy/$SERVICE_NAME manually if an update is needed."
else
  cp "deploy/$SERVICE_NAME" "$TARGET_SERVICE"
  systemctl daemon-reload
  echo "Installed systemd unit: $TARGET_SERVICE"
fi
systemctl daemon-reload
systemctl enable --now ge360-config-backup.timer
systemctl start ge360-config-backup.service || true

if [[ -f /etc/ge360/direct-bridge/bridge.env ]]; then
  echo "Existing GE360 Direct Bridge detected; refreshing permissions and systemd integration."
  GE360_APP_DIR="$APP_DIR" GE360_SERVICE_USER="$SERVICE_USER" bash "$APP_DIR/scripts/install-direct-bridge.sh"
fi

echo "Install complete. Review $APP_DIR/.env, then run:"
echo "  sudo systemctl enable --now $SERVICE_NAME"
echo "  sudo systemctl status $SERVICE_NAME"
echo "Future repository updates: sudo ge360-rilievi-update"
echo
echo "For GE360 DIRECT BRIDGE (WireGuard):"
echo "  sudo bash $APP_DIR/scripts/install-direct-bridge.sh"
echo "Then open locally:"
echo "  http://127.0.0.1:9888/control/?view=settings"
echo
echo "Legacy/optional Tailscale setup remains available:"
echo "  sudo bash $APP_DIR/scripts/setup-tailscale.sh"

echo "Documents archive: $DOCUMENTS_DIR"
echo "Configuration backups: $BACKUP_DIR (10 daily copies)"
echo "Restore latest: sudo ge360-config-restore latest"
