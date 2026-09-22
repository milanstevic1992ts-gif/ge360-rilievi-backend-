#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${GE360_CONFIG_BACKUP_DIR:-/opt/ge360/Backup/Configurazione}"
KEEP="${GE360_CONFIG_BACKUP_KEEP:-10}"
DATA_DIR="${GE360_DATA_DIR:-/opt/ge360/data/rilievi}"
DB_PATH="${GE360_DB_PATH:-$DATA_DIR/ge360-rilievi.sqlite3}"
API_KEY_FILE="${GE360_API_KEY_FILE:-$DATA_DIR/.api-key}"
DATE_UTC="$(date -u +%F)"
OUT="$BACKUP_DIR/ge360-config-$DATE_UTC.tar.gz"
LOCK=/run/lock/ge360-config-backup.lock

if [[ "${KEEP:-10}" -lt 10 ]]; then KEEP=10; fi
mkdir -p "$BACKUP_DIR"
chmod 0750 "$BACKUP_DIR" || true
exec 9>"$LOCK"
flock -n 9 || exit 0

STAGE="$(mktemp -d "$BACKUP_DIR/.stage.XXXXXX")"
cleanup(){ rm -rf "$STAGE"; }
trap cleanup EXIT
ROOT="$STAGE/rootfs"
mkdir -p "$ROOT"

copy_path(){
  local src="$1"
  [[ -e "$src" ]] || return 0
  local dst="$ROOT$src"
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
}

copy_path /etc/ge360-rilievi-backend
copy_path /etc/ge360
copy_path /etc/wireguard/wg0.conf
copy_path /var/lib/ge360/direct-bridge
copy_path /etc/systemd/system/ge360-rilievi-backend.service
copy_path /etc/systemd/system/ge360-direct-bridge-firewall.service
copy_path /etc/systemd/system/ge360-boot-verify.service
copy_path /etc/systemd/system/ge360-config-backup.service
copy_path /etc/systemd/system/ge360-config-backup.timer
copy_path "$API_KEY_FILE"
copy_path "$DATA_DIR/error-model.json"

# SQLite backup API gives a transaction-consistent snapshot while GE360 is running.
if [[ -f "$DB_PATH" ]]; then
  DB_DEST="$ROOT$DB_PATH"
  mkdir -p "$(dirname "$DB_DEST")"
  python3 - "$DB_PATH" "$DB_DEST" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
target = sqlite3.connect(dst)
with target:
    source.backup(target)
target.close()
source.close()
PY
fi

cat > "$STAGE/MANIFEST.txt" <<EOF
GE360 CONFIGURATION BACKUP
created_utc=$(date -u --iso-8601=seconds)
hostname=$(hostname)
database=$DB_PATH
retention=$KEEP
restore=sudo ge360-config-restore latest
contents=backend config, API key, Direct Bridge/WireGuard config and device state, SQLite metadata, systemd units, error model
EOF

TMP="$OUT.tmp"
rm -f "$TMP"
tar -C "$STAGE" -czf "$TMP" MANIFEST.txt rootfs
chmod 0640 "$TMP"
chown root:ge360 "$TMP" 2>/dev/null || true
mv -f "$TMP" "$OUT"

mapfile -t OLD < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'ge360-config-*.tar.gz' -printf '%T@ %p\n' | sort -rn | awk -v keep="$KEEP" 'NR>keep {$1=""; sub(/^ /,""); print}')
for path in "${OLD[@]:-}"; do
  [[ -n "$path" ]] && rm -f -- "$path"
done

echo "GE360 configuration backup: $OUT"
echo "Retained: $(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'ge360-config-*.tar.gz' | wc -l)/$KEEP"
