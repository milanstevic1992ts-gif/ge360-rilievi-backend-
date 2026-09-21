#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${GE360_APP_DIR:-/opt/ge360/ge360-rilievi-backend}"
SERVICE_NAME="ge360-rilievi-backend.service"
SERVICE_USER="${GE360_SERVICE_USER:-}"
if [[ -z "$SERVICE_USER" ]] && command -v systemctl >/dev/null 2>&1; then
  SERVICE_USER="$(systemctl show -p User --value "$SERVICE_NAME" 2>/dev/null || true)"
fi
SERVICE_USER="${SERVICE_USER:-jarvis}"

GROUP_NAME="ge360-bridge"
CONFIG_DIR="/etc/ge360/direct-bridge"
STATE_DIR="/var/lib/ge360/direct-bridge"
APPS_DIR="$CONFIG_DIR/apps.d"
ENV_FILE="$CONFIG_DIR/bridge.env"
MARKER="# Managed by GE360 DIRECT BRIDGE"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo/root: sudo bash scripts/install-direct-bridge.sh"
  exit 1
fi
[[ -f /etc/debian_version ]] || { echo "GE360 Direct Bridge installer currently supports Debian."; exit 1; }
command -v apt-get >/dev/null 2>&1 || { echo "apt-get not found"; exit 1; }
id "$SERVICE_USER" >/dev/null 2>&1 || { echo "Service user $SERVICE_USER not found"; exit 1; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y wireguard-tools nftables miniupnpc curl

getent group "$GROUP_NAME" >/dev/null || groupadd --system "$GROUP_NAME"
usermod -a -G "$GROUP_NAME" "$SERVICE_USER"

install -d -m 0750 -o root -g "$GROUP_NAME" "$CONFIG_DIR"
install -d -m 0750 -o root -g "$GROUP_NAME" "$APPS_DIR"
install -d -m 0770 -o root -g "$GROUP_NAME" "$CONFIG_DIR/wireguard"
mkdir -p /etc/wireguard
install -d -m 0770 -o root -g "$GROUP_NAME" "$STATE_DIR" "$STATE_DIR/backups" "$STATE_DIR/qr" "$STATE_DIR/state"

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
GE360_BRIDGE_ENABLED=true
GE360_BRIDGE_INTERFACE=wg0
GE360_BRIDGE_NETWORK=10.88.0.0/24
GE360_BRIDGE_SERVER_IP=10.88.0.1
GE360_BRIDGE_PORT=51820
GE360_BRIDGE_KEEPALIVE=25
GE360_PUBLIC_HOST=
GE360_BRIDGE_CONFIG_DIR=/etc/ge360/direct-bridge
GE360_BRIDGE_STATE_DIR=/var/lib/ge360/direct-bridge
GE360_BRIDGE_WG_CONFIG=/etc/ge360/direct-bridge/wireguard/wg0.conf
GE360_BRIDGE_AUTO_PORT_MAPPING=false
EOF
  chown root:"$GROUP_NAME" "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
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

[[ "$WG_IFACE" =~ ^[A-Za-z0-9_=+.-]{1,15}$ ]] || { echo "Invalid WireGuard interface: $WG_IFACE"; exit 1; }

if [[ -e "$SYSTEM_WG_CONFIG" || -L "$SYSTEM_WG_CONFIG" ]]; then
  system_target="$(readlink -f "$SYSTEM_WG_CONFIG" 2>/dev/null || true)"
  managed_target="$(readlink -m "$WG_CONFIG")"
  if [[ "$system_target" != "$managed_target" ]]; then
    if [[ -f "$SYSTEM_WG_CONFIG" ]] && grep -Fq "$MARKER" "$SYSTEM_WG_CONFIG" && [[ ! -e "$WG_CONFIG" ]]; then
      mv "$SYSTEM_WG_CONFIG" "$WG_CONFIG"
      echo "Migrated existing GE360-managed WireGuard config to $WG_CONFIG."
    else
      echo "Refusing to replace unmanaged WireGuard entry: $SYSTEM_WG_CONFIG"
      echo "Use another GE360_BRIDGE_INTERFACE or migrate that interface manually."
      exit 1
    fi
  fi
fi

if [[ -f "$WG_CONFIG" ]] && ! grep -Fq "$MARKER" "$WG_CONFIG"; then
  echo "Refusing to overwrite unmanaged WireGuard config: $WG_CONFIG"
  exit 1
fi

if [[ -s "$WG_CONFIG" ]]; then
  existing_private="$(awk -F' = ' '/^PrivateKey = / {print $2; exit}' "$WG_CONFIG")"
  if [[ -n "$existing_private" && ! -s "$PRIVATE_KEY" ]]; then
    umask 027
    printf '%s\n' "$existing_private" > "$PRIVATE_KEY"
  elif [[ -n "$existing_private" && -s "$PRIVATE_KEY" && "$existing_private" != "$(tr -d '\r\n' < "$PRIVATE_KEY")" ]]; then
    echo "Server key mismatch between $PRIVATE_KEY and $WG_CONFIG; refusing automatic rotation."
    exit 1
  fi
fi

if [[ ! -s "$PRIVATE_KEY" ]]; then
  umask 027
  wg genkey > "$PRIVATE_KEY"
  echo "Created persistent GE360 WireGuard server identity."
else
  echo "Existing server WireGuard private key preserved."
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
else
  echo "Existing managed $WG_CONFIG preserved."
fi
chown root:"$GROUP_NAME" "$WG_CONFIG"
chmod 0640 "$WG_CONFIG"

if [[ -L "$SYSTEM_WG_CONFIG" ]]; then
  [[ "$(readlink -f "$SYSTEM_WG_CONFIG")" == "$(readlink -m "$WG_CONFIG")" ]] || {
    echo "Unexpected WireGuard symlink target: $SYSTEM_WG_CONFIG"
    exit 1
  }
elif [[ -e "$SYSTEM_WG_CONFIG" ]]; then
  echo "Unexpected WireGuard file remains at $SYSTEM_WG_CONFIG"
  exit 1
else
  ln -s "$WG_CONFIG" "$SYSTEM_WG_CONFIG"
fi

# Register Rilievi as the first app on the shared GE360 tunnel.
RILIEVI_PROFILE="$APPS_DIR/rilievi.env"
if [[ ! -f "$RILIEVI_PROFILE" ]]; then
  cat > "$RILIEVI_PROFILE" <<'EOF'
APP_ID=rilievi
APP_NAME=GE360 Rilievi
APP_PORT=9888
APP_SERVICE=ge360-rilievi-backend.service
APP_HEALTH_URL=http://127.0.0.1:9888/healthz
APP_ENABLED=true
EOF
  chown root:"$GROUP_NAME" "$RILIEVI_PROFILE"
  chmod 0640 "$RILIEVI_PROFILE"
else
  echo "Existing Rilievi Bridge app profile preserved."
fi

install -m 0755 "$APP_DIR/scripts/direct-bridge-firewall.sh" /usr/local/sbin/ge360-direct-bridge-firewall
install -m 0755 "$APP_DIR/scripts/register-bridge-app.sh" /usr/local/sbin/ge360-bridge-register-app

cat > /etc/systemd/system/ge360-direct-bridge-firewall.service <<EOF
[Unit]
Description=GE360 Universal Direct Bridge firewall guard
Before=$SERVICE_NAME
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

mkdir -p "/etc/systemd/system/$SERVICE_NAME.d"
cat > "/etc/systemd/system/$SERVICE_NAME.d/direct-bridge.conf" <<EOF
[Unit]
After=wg-quick@${WG_IFACE}.service ge360-direct-bridge-firewall.service
Wants=wg-quick@${WG_IFACE}.service
Requires=ge360-direct-bridge-firewall.service
BindsTo=ge360-direct-bridge-firewall.service

[Service]
EnvironmentFile=-$ENV_FILE
SupplementaryGroups=$GROUP_NAME
AmbientCapabilities=CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_ADMIN
ReadWritePaths=$CONFIG_DIR $STATE_DIR
ExecStart=
ExecStart=$APP_DIR/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 9888
EOF

install -m 0755 "$APP_DIR/scripts/ge360-boot-verify.sh" /usr/local/sbin/ge360-boot-verify
install -m 0644 "$APP_DIR/packaging/deb/ge360-boot-verify.service" /etc/systemd/system/ge360-boot-verify.service

systemctl daemon-reload
systemctl enable --now ge360-direct-bridge-firewall.service
systemctl enable --now "wg-quick@${WG_IFACE}.service"
systemctl enable ge360-boot-verify.service >/dev/null 2>&1 || true

if systemctl is-active --quiet "$SERVICE_NAME"; then
  systemctl restart "$SERVICE_NAME"
fi
systemctl restart ge360-direct-bridge-firewall.service
systemctl restart ge360-boot-verify.service || true

wg show "$WG_IFACE" >/dev/null

echo
echo "GE360 UNIVERSAL DIRECT BRIDGE installed."
echo "Interface : $WG_IFACE"
echo "VPN server: $WG_SERVER_IP"
echo "WG port   : UDP $WG_PORT"
echo "Rilievi   : http://$WG_SERVER_IP:9888"
echo "App registry: $APPS_DIR"
echo "Server public key: $(cat "$PUBLIC_KEY")"
echo
echo "Existing WireGuard identity and Bridge database are preserved."
echo "Add another backend with: sudo ge360-bridge-register-app"
echo "Never forward backend TCP ports on the router; expose only WireGuard UDP $WG_PORT."
