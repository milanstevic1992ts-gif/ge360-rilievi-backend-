#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${GE360_APP_DIR:-/opt/ge360/ge360-rilievi-backend}"
REPO="${GE360_REPO:-milanstevic1992ts-gif/ge360-rilievi-backend-}"
BRANCH="${GE360_BRANCH:-main}"
SERVICE_NAME="ge360-rilievi-backend.service"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo/root: sudo ge360-rilievi-update"
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }

META_FILE="$TMP_DIR/meta"
python3 - "$REPO" "$BRANCH" "$TMP_DIR" "$META_FILE" <<'PY'
from __future__ import annotations
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

repo, branch, tmp, meta = sys.argv[1:]
tmp_path = Path(tmp)
api = f"https://api.github.com/repos/{repo}/commits/{branch}"
req = urllib.request.Request(api, headers={"User-Agent": "GE360-Rilievi-Updater"})
with urllib.request.urlopen(req, timeout=30) as response:
    commit = json.load(response)
sha = commit["sha"]
archive = tmp_path / "repo.tar.gz"
url = f"https://github.com/{repo}/archive/{sha}.tar.gz"
with urllib.request.urlopen(
    urllib.request.Request(url, headers={"User-Agent": "GE360-Rilievi-Updater"}),
    timeout=60,
) as response, archive.open("wb") as out:
    out.write(response.read())
with tarfile.open(archive, "r:gz") as tf:
    tf.extractall(tmp_path, filter="data")
roots = [p for p in tmp_path.iterdir() if p.is_dir()]
if len(roots) != 1:
    raise SystemExit("Unable to identify extracted GE360 source directory")
Path(meta).write_text(f"{sha}\n{roots[0]}\n", encoding="utf-8")
PY

mapfile -t META < "$META_FILE"
SOURCE_SHA="${META[0]}"
SOURCE_DIR="${META[1]}"

echo "GE360 Rilievi update: ${SOURCE_SHA:0:12}"
python3 "$SOURCE_DIR/scripts/verify-control-assets.py" "$SOURCE_DIR"
GE360_APP_DIR="$APP_DIR" bash "$SOURCE_DIR/scripts/install-debian.sh"

printf '%s\n' "$SOURCE_SHA" > "$APP_DIR/.ge360-deploy-sha"
chmod 0644 "$APP_DIR/.ge360-deploy-sha"

systemctl daemon-reload
systemctl restart "$SERVICE_NAME"
sleep 2

python3 "$APP_DIR/scripts/verify-control-assets.py" "$APP_DIR"
curl -fsS http://127.0.0.1:9888/healthz >/dev/null
echo "GE360 Rilievi aggiornato: ${SOURCE_SHA:0:12}"
echo "Control: http://127.0.0.1:9888/control/"
