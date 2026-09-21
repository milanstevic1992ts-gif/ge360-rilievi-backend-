#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${GE360_BRIDGE_INSTALL_ROOT:-/opt/ge360/universal-bridge-kit}"
GROUP_NAME="${GE360_BRIDGE_GROUP:-ge360-bridge}"
CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
STATE_DIR="${GE360_BRIDGE_STATE_DIR:-/var/lib/ge360/direct-bridge}"
ENV_FILE="$CONFIG_DIR/bridge.env"
MARKER="# Managed by GE360 DIRECT BRIDGE"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo/root."
  exit 1
fi
[[ -f /etc/debian_version ]] || { echo "This installer currently targets Debian/systemd."; exit 1; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard-tools nftables miniupnpc curl python3

getent group "$GROUP_NAME" >/dev/null || groupadd --system "$GROUP_NAME"

install -d -m 0750 -o root -g "$GROUP_NAME" "$CONFIG_DIR"
install -d -m 0750 -o root -g "$GROUP_NAME" "$CONFIG_DIR/apps.d"
install -d -m 0770 -o root -g "$GROUP_NAME" "$CONFIG_DIR/wireguard"
install -d -m 0770 -o root -g "$GROUP_NAME" "$STATE_DIR" "$STATE_DIR/backups" "$STATE_DIR/state"
mkdir -p /etc/wireguard

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0640 "$ROOT/config/bridge.env.example" "$ENV_FILE"
  chown root:"$GROUP_NAME" "$ENV_FILE"
else
  echo "Existing $ENV_FILE preserved."
fi

read_env_value() {
  local file="$1" key="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$file"
}

WG_IFACE="$(read_env_value "$ENV_FILE" GE360_BRIDGE_INTERFACE || true)"
WG_IFACE="${WG_IFACE:-wg0}"
WG_NETWORK="$(read_env_value "$ENV_FILE" GE360_BRIDGE_NETWORK || true)"
WG_NETWORK="${WG_NETWORK:-10.88.0.0/24}"
WG_SERVER_IP="$(read_env_value "$ENV_FILE" GE360_BRIDGE_SERVER_IP || true)"
WG_SERVER_IP="${WG_SERVER_IP:-10.88.0.1}"
WG_PORT="$(read_env_value "$ENV_FILE" GE360_BRIDGE_PORT || true)"
WG_PORT="${WG_PORT:-51820}"
WG_CONFIG="$(read_env_value "$ENV_FILE" GE360_BRIDGE_WG_CONFIG || true)"
WG_CONFIG="${WG_CONFIG:-$CONFIG_DIR/wireguard/${WG_IFACE}.conf}"

SYSTEM_WG_CONFIG="/etc/wireguard/${WG_IFACE}.conf"
PRIVATE_KEY="$CONFIG_DIR/server.key"
PUBLIC_KEY="$CONFIG_DIR/server.pub"

[[ "$WG_IFACE" =~ ^[A-Za-z0-9_=+.-]{1,15}$ ]] || { echo "Invalid WireGuard interface"; exit 1; }

if [[ -e "$SYSTEM_WG_CONFIG" || -L "$SYSTEM_WG_CONFIG" ]]; then
  current="$(readlink -f "$SYSTEM_WG_CONFIG" 2>/dev/null || true)"
  wanted="$(readlink -m "$WG_CONFIG")"
  if [[ "$current" != "$wanted" ]]; then
    if [[ -f "$SYSTEM_WG_CONFIG" ]] && grep -Fq "$MARKER" "$SYSTEM_WG_CONFIG" && [[ ! -e "$WG_CONFIG" ]]; then
      mv "$SYSTEM_WG_CONFIG" "$WG_CONFIG"
      echo "Migrated existing GE360-managed WireGuard config."
    else
      echo "Refusing to replace unmanaged $SYSTEM_WG_CONFIG"
      exit 1
    fi
  fi
fi

if [[ -f "$WG_CONFIG" ]] && ! grep -Fq "$MARKER" "$WG_CONFIG"; then
  echo "Refusing to overwrite unmanaged $WG_CONFIG"
  exit 1
fi

if [[ -s "$WG_CONFIG" ]]; then
  existing_private="$(awk -F' = ' '/^PrivateKey = / {print $2; exit}' "$WG_CONFIG")"
  if [[ -n "$existing_private" && ! -s "$PRIVATE_KEY" ]]; then
    umask 027
    printf '%s\n' "$existing_private" > "$PRIVATE_KEY"
  elif [[ -n "$existing_private" && -s "$PRIVATE_KEY" && "$existing_private" != "$(tr -d '\r\n' < "$PRIVATE_KEY")" ]]; then
    echo "Server key mismatch: refusing automatic rotation."
    exit 1
  fi
fi

if [[ ! -s "$PRIVATE_KEY" ]]; then
  umask 027
  wg genkey > "$PRIVATE_KEY"
  echo "Created persistent GE360 WireGuard identity."
else
  echo "Existing GE360 WireGuard identity preserved."
fi
if [[ ! -s "$PUBLIC_KEY" ]]; then
  wg pubkey < "$PRIVATE_KEY" > "$PUBLIC_KEY"
fi
chown root:"$GROUP_NAME" "$PRIVATE_KEY" "$PUBLIC_KEY"
chmod 0640 "$PRIVATE_KEY" "$PUBLIC_KEY"

if [[ ! -f "$WG_CONFIG" ]]; then
  private="$(tr -d '\r\n' < "$PRIVATE_KEY")"
  cat > "$WG_CONFIG" <<EOF
$MARKER
[Interface]
Address = $WG_SERVER_IP/${WG_NETWORK#*/}
ListenPort = $WG_PORT
PrivateKey = $private
EOF
fi
chown root:"$GROUP_NAME" "$WG_CONFIG"
chmod 0640 "$WG_CONFIG"

if [[ -L "$SYSTEM_WG_CONFIG" ]]; then
  [[ "$(readlink -f "$SYSTEM_WG_CONFIG")" == "$(readlink -m "$WG_CONFIG")" ]] || {
    echo "Unexpected WireGuard symlink target."
    exit 1
  }
elif [[ -e "$SYSTEM_WG_CONFIG" ]]; then
  echo "Unexpected unmanaged WireGuard file at $SYSTEM_WG_CONFIG"
  exit 1
else
  ln -s "$WG_CONFIG" "$SYSTEM_WG_CONFIG"
fi

install -m 0755 "$ROOT/scripts/direct-bridge-firewall.sh" /usr/local/sbin/ge360-direct-bridge-firewall
install -m 0755 "$ROOT/scripts/ge360-boot-verify.sh" /usr/local/sbin/ge360-boot-verify
install -m 0755 "$ROOT/scripts/register-bridge-app.sh" /usr/local/sbin/ge360-bridge-register-app

install -m 0755 "$ROOT/scripts/ge360-bridge-network-auto.sh" /usr/local/sbin/ge360-bridge-network-auto
install -m 0755 "$ROOT/scripts/ge360-bridge-wizard.sh" /usr/local/sbin/ge360-bridge-wizard
install -m 0755 "$ROOT/scripts/ge360-bridge-terminal-launcher.sh" /usr/local/bin/ge360-bridge-setup-terminal

# Keep a standalone reusable copy outside every application repository.
if [[ "$(readlink -f "$ROOT")" != "$(readlink -m "$INSTALL_ROOT")" ]]; then
  install -d -m 0755 "$INSTALL_ROOT/scripts" "$INSTALL_ROOT/config" "$INSTALL_ROOT/packaging/desktop"
  install -m 0755 "$ROOT/scripts/install-universal-bridge-core.sh" "$INSTALL_ROOT/scripts/install-universal-bridge-core.sh"
  install -m 0755 "$ROOT/scripts/register-bridge-app.sh" "$INSTALL_ROOT/scripts/register-bridge-app.sh"
  install -m 0755 "$ROOT/scripts/direct-bridge-firewall.sh" "$INSTALL_ROOT/scripts/direct-bridge-firewall.sh"
  install -m 0755 "$ROOT/scripts/ge360-boot-verify.sh" "$INSTALL_ROOT/scripts/ge360-boot-verify.sh"
  install -m 0755 "$ROOT/scripts/ge360-bridge-network-auto.sh" "$INSTALL_ROOT/scripts/ge360-bridge-network-auto.sh"
  install -m 0755 "$ROOT/scripts/ge360-bridge-wizard.sh" "$INSTALL_ROOT/scripts/ge360-bridge-wizard.sh"
  install -m 0755 "$ROOT/scripts/ge360-bridge-terminal-launcher.sh" "$INSTALL_ROOT/scripts/ge360-bridge-terminal-launcher.sh"
  install -m 0644 "$ROOT/config/bridge.env.example" "$INSTALL_ROOT/config/bridge.env.example"
  install -m 0644 "$ROOT/packaging/desktop/ge360-universal-bridge.desktop" "$INSTALL_ROOT/packaging/desktop/ge360-universal-bridge.desktop"
fi

cat > /usr/local/sbin/ge360-bridge-core-install <<EOF
#!/usr/bin/env bash
exec bash "$INSTALL_ROOT/scripts/install-universal-bridge-core.sh" "\$@"
EOF
chmod 0755 /usr/local/sbin/ge360-bridge-core-install

install -m 0644 "$ROOT/packaging/desktop/ge360-universal-bridge.desktop" /usr/share/applications/ge360-universal-bridge.desktop
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true

cat > /etc/systemd/system/ge360-direct-bridge-firewall.service <<EOF
[Unit]
Description=GE360 Universal Direct Bridge firewall guard
After=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
EnvironmentFile=-$ENV_FILE
ExecStart=/usr/local/sbin/ge360-direct-bridge-firewall
ExecStop=-/usr/sbin/nft delete table inet ge360_direct_bridge
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/ge360-boot-verify.service <<EOF
[Unit]
Description=GE360 Universal Direct Bridge post-boot verification
After=network-online.target wg-quick@${WG_IFACE}.service ge360-direct-bridge-firewall.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ge360-boot-verify
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ge360-direct-bridge-firewall.service
systemctl enable --now "wg-quick@${WG_IFACE}.service"
systemctl enable ge360-boot-verify.service >/dev/null 2>&1 || true
systemctl restart ge360-boot-verify.service || true

echo
echo "GE360 Universal Direct Bridge core installed."
echo "Interface : $WG_IFACE"
echo "VPN server: $WG_SERVER_IP"
echo "WireGuard : UDP $WG_PORT"
echo "Apps dir  : $CONFIG_DIR/apps.d"
echo "Kit       : $INSTALL_ROOT"
echo "Public key: $(cat "$PUBLIC_KEY")"
echo
echo "Launcher installato: GE360 Universal Bridge (menu applicazioni)."
echo "Wizard terminale: sudo ge360-bridge-wizard"
echo "Register each backend with /usr/local/sbin/ge360-bridge-register-app."
