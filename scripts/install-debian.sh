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
  echo "Created $APP_DIR/.env — set GE360_API_KEY before starting the service."
else
  echo "Existing .env preserved."
fi

chown -R "${SUDO_USER:-root}:${SUDO_USER:-root}" "$DATA_DIR" || true

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
echo "For guided Tailscale + frontend connection:"
echo "  sudo bash $APP_DIR/scripts/setup-tailscale.sh"
echo "Then open locally:"
echo "  http://127.0.0.1:9888/setup/"
