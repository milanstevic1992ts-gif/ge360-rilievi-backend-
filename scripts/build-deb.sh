#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist}"
VERSION="${GE360_DEB_VERSION:-$(python3 - <<'PY'
from pathlib import Path
import re
text = Path("pyproject.toml").read_text(encoding="utf-8")
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
if not m:
    raise SystemExit("Unable to read project version from pyproject.toml")
print(m.group(1))
PY
)}"
ARCH="${GE360_DEB_ARCH:-all}"
PACKAGE=ge360-rilievi-backend
BASENAME="${PACKAGE}_${VERSION}_${ARCH}"
STAGE="$(mktemp -d)"
PKG_ROOT="$STAGE/$BASENAME"
APP_DIR="$PKG_ROOT/opt/ge360/ge360-rilievi-backend"

cleanup() {
  rm -rf "$STAGE"
}
trap cleanup EXIT

command -v dpkg-deb >/dev/null 2>&1 || {
  echo "dpkg-deb not found. Install: sudo apt install dpkg-dev"
  exit 1
}
command -v rsync >/dev/null 2>&1 || {
  echo "rsync not found. Install: sudo apt install rsync"
  exit 1
}

mkdir -p "$OUT_DIR" "$APP_DIR" "$PKG_ROOT/DEBIAN" "$PKG_ROOT/lib/systemd/system"

rsync -a   --exclude '.git'   --exclude '.github'   --exclude '.venv'   --exclude '.env'   --exclude 'dist'   --exclude 'local-data'   --exclude '__pycache__'   --exclude '.pytest_cache'   --exclude 'tests'   "$ROOT/" "$APP_DIR/"

install -m 0644 "$ROOT/packaging/deb/ge360-rilievi-backend.service"   "$PKG_ROOT/lib/systemd/system/ge360-rilievi-backend.service"
install -m 0755 "$ROOT/packaging/deb/preinst" "$PKG_ROOT/DEBIAN/preinst"
install -m 0755 "$ROOT/packaging/deb/postinst" "$PKG_ROOT/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/deb/prerm" "$PKG_ROOT/DEBIAN/prerm"
install -m 0755 "$ROOT/packaging/deb/postrm" "$PKG_ROOT/DEBIAN/postrm"
chmod 0755 "$APP_DIR/scripts/preflight.sh" "$APP_DIR/scripts/install-direct-bridge.sh" "$APP_DIR/scripts/ge360-rilievi-status" "$APP_DIR/scripts/ge360-rilievi-diagnose"
mkdir -p "$PKG_ROOT/usr/bin"
install -m 0755 "$ROOT/scripts/ge360-rilievi-status" "$PKG_ROOT/usr/bin/ge360-rilievi-status"
install -m 0755 "$ROOT/scripts/ge360-rilievi-diagnose" "$PKG_ROOT/usr/bin/ge360-rilievi-diagnose"

mkdir -p "$PKG_ROOT/usr/share/applications" "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps"
install -m 0644 "$ROOT/packaging/desktop/ge360-rilievi-backend.desktop" "$PKG_ROOT/usr/share/applications/ge360-rilievi-backend.desktop"
install -m 0644 "$ROOT/packaging/desktop/ge360-rilievi.svg" "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/ge360-rilievi.svg"

mkdir -p "$PKG_ROOT/usr/local/sbin"
install -m 0755 "$ROOT/scripts/ge360-boot-verify.sh" "$PKG_ROOT/usr/local/sbin/ge360-boot-verify"
install -m 0644 "$ROOT/packaging/deb/ge360-boot-verify.service" "$PKG_ROOT/lib/systemd/system/ge360-boot-verify.service"

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: GE360 <edilmilanstevic@gmail.com>
Depends: python3 (>= 3.12), python3-venv, python3-pip, ca-certificates
Recommends: wireguard-tools, nftables, miniupnpc
Homepage: https://github.com/milanstevic1992ts-gif/ge360-rilievi-backend-
Description: GE360 Rilievi Backend
 FastAPI backend for GE360 construction surveys, metric floor-plan processing,
 CAD/PDF exports, local AI integration and optional GE360 Direct Bridge.
EOF

INSTALLED_KB="$(du -sk "$PKG_ROOT" | awk '{print $1}')"
printf 'Installed-Size: %s\n' "$INSTALLED_KB" >> "$PKG_ROOT/DEBIAN/control"

OUTPUT="$OUT_DIR/$BASENAME.deb"
dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUTPUT"
dpkg-deb --info "$OUTPUT" >/dev/null

echo
echo "Built: $OUTPUT"
echo "Install:"
echo "  sudo apt install ./$(basename "$OUTPUT")"
echo
echo "After install:"
echo "  systemctl status ge360-rilievi-backend --no-pager"
echo "  http://127.0.0.1:9888/control/"
