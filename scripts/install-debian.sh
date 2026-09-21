#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${GE360_APP_DIR:-/opt/ge360/ge360-rilievi-backend}"
DATA_DIR="${GE360_DATA_DIR:-/opt/ge360/data/rilievi}"
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

mkdir -p "$APP_DIR" "$DATA_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
  rsync -a --delete --exclude '.git' --exclude '.env' --exclude '.venv' "$SCRIPT_DIR/" "$APP_DIR/"
fi

cd "$APP_DIR"
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
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" || true

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

TARGET_SERVICE="/etc/systemd/system/$SERVICE_NAME"
if [[ -e "$TARGET_SERVICE" ]]; then
  echo "Existing $TARGET_SERVICE preserved. Review deploy/$SERVICE_NAME manually if an update is needed."
else
  cp "deploy/$SERVICE_NAME" "$TARGET_SERVICE"
  systemctl daemon-reload
  echo "Installed systemd unit: $TARGET_SERVICE"
fi

echo "Install complete. Review $APP_DIR/.env, then run:"
echo "  sudo systemctl enable --now $SERVICE_NAME"
echo "  sudo systemctl status $SERVICE_NAME"
echo
echo "For GE360 DIRECT BRIDGE (WireGuard):"
echo "  sudo bash $APP_DIR/scripts/install-direct-bridge.sh"
echo "Then open locally:"
echo "  http://127.0.0.1:9888/setup/"
echo
echo "Legacy/optional Tailscale setup remains available:"
echo "  sudo bash $APP_DIR/scripts/setup-tailscale.sh"
