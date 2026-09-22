#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${GE360_CONFIG_BACKUP_DIR:-/opt/ge360/Backup/Configurazione}"
CHOICE="${1:-latest}"

if [[ $EUID -ne 0 ]]; then
  exec sudo -E "$0" "$@"
fi

if [[ "$CHOICE" == "latest" ]]; then
  FILE="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'ge360-config-*.tar.gz' -printf '%T@ %p\n' | sort -rn | head -n1 | cut -d' ' -f2-)"
else
  FILE="$CHOICE"
  [[ "$FILE" = /* ]] || FILE="$BACKUP_DIR/$FILE"
fi

if [[ -z "${FILE:-}" || ! -f "$FILE" ]]; then
  echo "Backup GE360 non trovato: ${FILE:-$CHOICE}" >&2
  exit 2
fi

if tar -tzf "$FILE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Archivio non sicuro: contiene percorsi assoluti o .." >&2
  exit 3
fi

TMP="$(mktemp -d /tmp/ge360-restore.XXXXXX)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

tar -C "$TMP" -xzf "$FILE"
[[ -d "$TMP/rootfs" ]] || { echo "Backup GE360 non valido" >&2; exit 4; }

echo "Ripristino da: $FILE"
echo "Manifest:"
cat "$TMP/MANIFEST.txt" 2>/dev/null || true

systemctl stop ge360-rilievi-backend.service 2>/dev/null || true
systemctl stop wg-quick@wg0.service 2>/dev/null || true
systemctl stop ge360-direct-bridge-firewall.service 2>/dev/null || true

cp -a "$TMP/rootfs/." /
chown -R ge360:ge360 /opt/ge360/data/rilievi 2>/dev/null || true
chown -R root:ge360 /etc/ge360-rilievi-backend 2>/dev/null || true
chmod 0640 /etc/ge360-rilievi-backend/ge360.env 2>/dev/null || true
chmod 0600 /opt/ge360/data/rilievi/.api-key 2>/dev/null || true

systemctl daemon-reload || true
systemctl enable ge360-config-backup.timer >/dev/null 2>&1 || true
systemctl start ge360-direct-bridge-firewall.service 2>/dev/null || true
systemctl start wg-quick@wg0.service 2>/dev/null || true
systemctl restart ge360-rilievi-backend.service

echo
echo "Ripristino GE360 completato."
systemctl --no-pager --full status ge360-rilievi-backend.service || true
