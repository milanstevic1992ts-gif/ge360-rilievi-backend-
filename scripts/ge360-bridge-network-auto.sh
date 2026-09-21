#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${GE360_BRIDGE_CONFIG_DIR:-/etc/ge360/direct-bridge}"
STATE_DIR="${GE360_BRIDGE_STATE_DIR:-/var/lib/ge360/direct-bridge}"
ENV_FILE="$CONFIG_DIR/bridge.env"
STATE_FILE="$STATE_DIR/state/network.json"
APPLY=false

[[ "${1:-}" == "--apply" ]] && APPLY=true

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "$0" "$@"
fi

mkdir -p "$STATE_DIR/state"

read_env_value() {
  local file="$1" key="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); gsub(/^["'\'']|["'\'']$/,""); print; exit}' "$file"
}

set_env_value() {
  local key="$1" value="$2"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1]); key=sys.argv[2]; value=sys.argv[3]
lines=path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out=[]; replaced=False
for line in lines:
    if line.split("=",1)[0].strip()==key and "=" in line:
        out.append(f"{key}={value}")
        replaced=True
    else:
        out.append(line)
if not replaced:
    out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip()+"\n", encoding="utf-8")
PY
}

WG_PORT="$(read_env_value "$ENV_FILE" GE360_BRIDGE_PORT || true)"
WG_PORT="${WG_PORT:-51820}"

LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \\([0-9.]*\\).*/\\1/p' | head -1 || true)"

IPV6="$(python3 - <<'PY'
import json, subprocess, ipaddress
try:
    raw=subprocess.check_output(["ip","-j","-6","addr","show","scope","global"], text=True)
    data=json.loads(raw)
except Exception:
    print(""); raise SystemExit
stable=[]; fallback=[]
for iface in data:
    for info in iface.get("addr_info",[]):
        value=info.get("local")
        if not value: continue
        try: ip=ipaddress.ip_address(value)
        except ValueError: continue
        if not isinstance(ip, ipaddress.IPv6Address) or not ip.is_global: continue
        flags=set(info.get("flags") or [])
        temporary=bool(info.get("temporary")) or "temporary" in flags or "mngtmpaddr" in flags
        deprecated="deprecated" in flags or info.get("preferred_life_time")==0
        if not temporary and not deprecated: stable.append(str(ip))
        elif not deprecated: fallback.append(str(ip))
print((stable or fallback or [""])[0])
PY
)"

EXTERNAL_IPV4=""
UPNP_ERROR=""
if command -v upnpc >/dev/null 2>&1; then
  UPNP_OUT="$(upnpc -s 2>&1 || true)"
  EXTERNAL_IPV4="$(printf '%s\n' "$UPNP_OUT" | sed -n 's/.*ExternalIPAddress *= *\([0-9.]*\).*/\1/p' | head -1)"
  [[ -n "$EXTERNAL_IPV4" ]] || UPNP_ERROR="router did not report ExternalIPAddress"
else
  UPNP_ERROR="upnpc not installed"
fi

IPV4_CLASS="$(python3 - "$EXTERNAL_IPV4" <<'PY'
import ipaddress, sys
v=sys.argv[1]
if not v:
    print("UNKNOWN"); raise SystemExit
try: ip=ipaddress.ip_address(v)
except ValueError:
    print("UNKNOWN"); raise SystemExit
if not isinstance(ip, ipaddress.IPv4Address):
    print("UNKNOWN")
elif ip in ipaddress.ip_network("100.64.0.0/10"):
    print("CGNAT")
elif ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
    print("NON_PUBLIC")
else:
    print("PUBLIC")
PY
)"


# Cooperate with common host firewalls when they are already enabled.
HOST_FIREWALL="nftables"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi '^Status: active'; then
  ufw allow "${WG_PORT}/udp" comment 'GE360 Universal Bridge' >/dev/null 2>&1 || true
  HOST_FIREWALL="ufw"
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  firewall-cmd --permanent --add-port="${WG_PORT}/udp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  HOST_FIREWALL="firewalld"
fi

ENDPOINT=""
METHOD=""
REMOTE_STATE="BLOCKED"
PORT_MAPPING="not-attempted"
PORT_MAPPING_ERROR=""

if [[ -n "$IPV6" ]]; then
  ENDPOINT="$IPV6"
  METHOD="ipv6"
  REMOTE_STATE="READY_IPV6"
elif [[ "$IPV4_CLASS" == "PUBLIC" && -n "$EXTERNAL_IPV4" ]]; then
  ENDPOINT="$EXTERNAL_IPV4"
  METHOD="ipv4"
  REMOTE_STATE="READY_IPV4_NEEDS_MAPPING"
  if [[ -n "$LAN_IP" && -n "$(command -v upnpc 2>/dev/null || true)" ]]; then
    MAP_OUT="$(upnpc -e "GE360 Direct Bridge" -a "$LAN_IP" "$WG_PORT" "$WG_PORT" UDP 2>&1 || true)"
    if printf '%s' "$MAP_OUT" | grep -Eqi 'is redirected to|AddPortMapping.*success|external.*->'; then
      PORT_MAPPING="mapped"
      REMOTE_STATE="READY_IPV4"
    else
      PORT_MAPPING="failed"
      PORT_MAPPING_ERROR="$(printf '%s' "$MAP_OUT" | tail -n 3 | tr '\n' ' ' | sed 's/"/'''/g')"
    fi
  fi
elif [[ "$IPV4_CLASS" == "CGNAT" || "$IPV4_CLASS" == "NON_PUBLIC" ]]; then
  REMOTE_STATE="BLOCKED_CGNAT"
  METHOD="none"
else
  REMOTE_STATE="PUBLIC_ENDPOINT_UNKNOWN"
  METHOD="none"
fi

if $APPLY && [[ -n "$ENDPOINT" ]]; then
  set_env_value GE360_PUBLIC_HOST "$ENDPOINT"
  if [[ "$METHOD" == "ipv6" ]]; then
    set_env_value GE360_BRIDGE_AUTO_PORT_MAPPING false
  elif [[ "$PORT_MAPPING" == "mapped" ]]; then
    set_env_value GE360_BRIDGE_AUTO_PORT_MAPPING true
  fi
fi

python3 - "$STATE_FILE" "$LAN_IP" "$IPV6" "$EXTERNAL_IPV4" "$IPV4_CLASS" "$ENDPOINT" "$METHOD" "$REMOTE_STATE" "$PORT_MAPPING" "$UPNP_ERROR" "$PORT_MAPPING_ERROR" "$WG_PORT" "$HOST_FIREWALL" <<'PY'
from pathlib import Path
import json,sys,datetime
p=Path(sys.argv[1])
data={
 "checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "lan_ipv4":sys.argv[2] or None,
 "global_ipv6":sys.argv[3] or None,
 "external_ipv4":sys.argv[4] or None,
 "external_ipv4_class":sys.argv[5],
 "public_host":sys.argv[6] or None,
 "method":sys.argv[7],
 "remote_state":sys.argv[8],
 "port_mapping":sys.argv[9],
 "upnp_error":sys.argv[10] or None,
 "port_mapping_error":sys.argv[11] or None,
 "wireguard_udp_port":int(sys.argv[12]),
 "host_firewall":sys.argv[13],
}
p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
print(json.dumps(data,indent=2))
PY

echo
case "$REMOTE_STATE" in
  READY_IPV6)
    echo "[OK] IPv6 pubblico rilevato. GE360 userà: [$ENDPOINT]:$WG_PORT"
    echo "     Verificare che il firewall IPv6 del router consenta UDP $WG_PORT."
    ;;
  READY_IPV4)
    echo "[OK] IPv4 pubblico + port mapping UPnP configurato: $ENDPOINT:$WG_PORT"
    ;;
  READY_IPV4_NEEDS_MAPPING)
    echo "[ATTENZIONE] IPv4 pubblico rilevato, ma il port mapping automatico non è stato confermato."
    echo "             Inoltra UDP $WG_PORT verso $LAN_IP sul router."
    ;;
  BLOCKED_CGNAT)
    echo "[BLOCCATO] La linea risulta sotto CGNAT/non-public e non è stato trovato IPv6 pubblico."
    echo "           Un software locale non può creare un IP pubblico: serve IPv6 raggiungibile"
    echo "           oppure un IPv4 pubblico fornito dall'operatore."
    ;;
  *)
    echo "[ATTENZIONE] Endpoint pubblico non determinato automaticamente."
    echo "             Imposta GE360_PUBLIC_HOST in $ENV_FILE."
    ;;
esac
