#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

install -m 0755 "$ROOT/scripts/ge360-bridge-terminal-launcher.sh" /usr/local/bin/ge360-bridge-setup-terminal
install -m 0644 "$ROOT/packaging/desktop/ge360-universal-bridge.desktop" /usr/share/applications/ge360-universal-bridge.desktop

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true

echo "Voce applicazioni installata: GE360 Universal Bridge"
