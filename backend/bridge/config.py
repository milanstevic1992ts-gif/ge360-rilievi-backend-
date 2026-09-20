from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path

_IFACE_RE = re.compile(r"^[A-Za-z0-9_=+.-]{1,15}$")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BridgeSettings:
    enabled: bool
    interface: str
    network: ipaddress.IPv4Network
    server_ip: ipaddress.IPv4Address
    listen_port: int
    backend_port: int
    public_host: str | None
    config_dir: Path
    state_dir: Path
    wg_config_path: Path
    server_private_key_path: Path
    server_public_key_path: Path
    db_path: Path
    auto_port_mapping: bool = False
    persistent_keepalive: int = 25

    @classmethod
    def from_env(cls, backend_port: int = 9888) -> "BridgeSettings":
        interface = os.getenv("GE360_BRIDGE_INTERFACE", "wg0").strip()
        if not _IFACE_RE.fullmatch(interface):
            raise ValueError("GE360_BRIDGE_INTERFACE is not a valid Linux interface name")
        network = ipaddress.ip_network(os.getenv("GE360_BRIDGE_NETWORK", "10.88.0.0/24"), strict=True)
        if not isinstance(network, ipaddress.IPv4Network):
            raise ValueError("GE360_BRIDGE_NETWORK must be IPv4")
        server_ip = ipaddress.ip_address(os.getenv("GE360_BRIDGE_SERVER_IP", "10.88.0.1"))
        if not isinstance(server_ip, ipaddress.IPv4Address) or server_ip not in network:
            raise ValueError("GE360_BRIDGE_SERVER_IP must be an IPv4 address inside GE360_BRIDGE_NETWORK")
        listen_port = int(os.getenv("GE360_BRIDGE_PORT", "51820"))
        if not 1 <= listen_port <= 65535:
            raise ValueError("GE360_BRIDGE_PORT must be between 1 and 65535")
        keepalive = int(os.getenv("GE360_BRIDGE_KEEPALIVE", "25"))
        if not 0 <= keepalive <= 65535:
            raise ValueError("GE360_BRIDGE_KEEPALIVE is invalid")
        config_dir = Path(os.getenv("GE360_BRIDGE_CONFIG_DIR", "/etc/ge360/direct-bridge"))
        state_dir = Path(os.getenv("GE360_BRIDGE_STATE_DIR", "/var/lib/ge360/direct-bridge"))
        wg_config = Path(os.getenv("GE360_BRIDGE_WG_CONFIG", f"/etc/wireguard/{interface}.conf"))
        public_host = os.getenv("GE360_PUBLIC_HOST", "").strip() or None
        return cls(
            enabled=_bool("GE360_BRIDGE_ENABLED", True),
            interface=interface,
            network=network,
            server_ip=server_ip,
            listen_port=listen_port,
            backend_port=backend_port,
            public_host=public_host,
            config_dir=config_dir,
            state_dir=state_dir,
            wg_config_path=wg_config,
            server_private_key_path=config_dir / "server.key",
            server_public_key_path=config_dir / "server.pub",
            db_path=state_dir / "bridge.sqlite3",
            auto_port_mapping=_bool("GE360_BRIDGE_AUTO_PORT_MAPPING", False),
            persistent_keepalive=keepalive,
        )

    @property
    def server_cidr(self) -> str:
        return f"{self.server_ip}/{self.network.prefixlen}"

    @property
    def backend_url(self) -> str:
        return f"http://{self.server_ip}:{self.backend_port}"
