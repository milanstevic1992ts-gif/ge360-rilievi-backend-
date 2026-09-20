from __future__ import annotations

from .config import BridgeSettings
from .network import (
    backend_port_open,
    classify_external_ipv4,
    default_route,
    global_ipv6_addresses,
    local_ipv4_for_default_route,
    port_mapping_capabilities,
    resolve_public_endpoint,
    try_upnp_mapping,
    upnp_external_ipv4,
)
from .qr import wireguard_qr_png_base64
from .store import BridgeStore
from .wireguard import WireGuardController


class BridgeUnavailable(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


class DirectBridgeManager:
    def __init__(self, settings: BridgeSettings, store: BridgeStore | None = None, wireguard: WireGuardController | None = None):
        self.settings = settings
        self.store = store or BridgeStore(settings.db_path)
        self.wireguard = wireguard or WireGuardController(settings)

    @staticmethod
    def public_device(device: dict) -> dict:
        return {
            "device_id": device["device_id"], "name": device["name"], "vpn_ip": device["vpn_ip"],
            "public_key": device["public_key"], "created_at": device["created_at"],
            "last_seen_at": device.get("last_seen_at"), "status": device["status"],
            "revoked_at": device.get("revoked_at"), "last_handshake_at": device.get("last_handshake_at"),
            "rx_bytes": int(device.get("rx_bytes") or 0), "tx_bytes": int(device.get("tx_bytes") or 0),
        }

    def _endpoint_or_raise(self):
        endpoint = resolve_public_endpoint(self.settings)
        if not endpoint.available or not endpoint.endpoint:
            raise BridgeUnavailable(endpoint.state_code, endpoint.message or "Remote endpoint unavailable")
        return endpoint

    def refresh_traffic(self) -> None:
        try:
            dump = self.wireguard.dump()
        except RuntimeError:
            return
        for peer in dump.get("peers", []):
            self.store.update_traffic(peer["public_key"], handshake_epoch=int(peer.get("latest_handshake") or 0), rx_bytes=int(peer.get("rx_bytes") or 0), tx_bytes=int(peer.get("tx_bytes") or 0))

    def status(self) -> dict:
        self.refresh_traffic()
        endpoint = resolve_public_endpoint(self.settings)
        installed = self.wireguard.installed()
        active = self.wireguard.interface_active() if installed else False
        active_devices = self.store.list(active_only=True)
        handshakes = [row.get("last_handshake_at") for row in active_devices if row.get("last_handshake_at")]
        state_code = "ONLINE" if active and endpoint.available else endpoint.state_code
        if not self.settings.enabled:
            state_code = "DISABLED"
        elif not installed:
            state_code = "WIREGUARD_NOT_INSTALLED"
        elif not active:
            state_code = "WIREGUARD_INACTIVE"
        return {
            "enabled": self.settings.enabled, "interface": self.settings.interface,
            "server_ip": str(self.settings.server_ip), "port": self.settings.listen_port,
            "backend_port": self.settings.backend_port, "backend_url": self.settings.backend_url,
            "status": "online" if state_code == "ONLINE" else "offline", "state_code": state_code,
            "device_count": len(active_devices), "public_endpoint": endpoint.endpoint,
            "endpoint_source": endpoint.source, "remote_reachability_verified": endpoint.externally_verified,
            "last_handshake": max(handshakes) if handshakes else None,
            "rx_bytes": sum(int(row.get("rx_bytes") or 0) for row in active_devices),
            "tx_bytes": sum(int(row.get("tx_bytes") or 0) for row in active_devices),
            "message": endpoint.message,
        }

    def list_devices(self) -> list[dict]:
        self.refresh_traffic()
        return [self.public_device(row) for row in self.store.list()]

    def get_device(self, device_id: str) -> dict | None:
        self.refresh_traffic()
        row = self.store.get(device_id)
        return self.public_device(row) if row else None

    def create_device(self, name: str) -> dict:
        if not self.settings.enabled:
            raise BridgeUnavailable("BRIDGE_DISABLED", "GE360 DIRECT BRIDGE is disabled")
        endpoint = self._endpoint_or_raise()
        if not self.wireguard.installed():
            raise BridgeUnavailable("WIREGUARD_NOT_INSTALLED", "WireGuard is not installed")
        mapping = try_upnp_mapping(self.settings)
        client_private, client_public = self.wireguard.generate_keypair()
        device = self.store.allocate_and_add(name.strip(), client_public, self.settings.network, self.settings.server_ip)
        try:
            self.wireguard.write_config(self.store.list(active_only=True))
            self.wireguard.apply_peer(client_public, device["vpn_ip"])
        except Exception:
            self.store.revoke(device["device_id"])
            try:
                self.wireguard.write_config(self.store.list(active_only=True))
            except Exception:
                pass
            raise
        server_public = self.wireguard.server_public_key()
        config = self.client_config(client_private, device["vpn_ip"], server_public, endpoint.endpoint)
        return {
            "device": self.public_device(device),
            "pairing": {
                "shown_once": True, "wireguard_config": config,
                "qr_png_base64": wireguard_qr_png_base64(config),
                "backend_url": self.settings.backend_url, "endpoint": endpoint.endpoint,
                "port_mapping": mapping,
            },
        }

    def client_config(self, client_private: str, vpn_ip: str, server_public: str, endpoint: str) -> str:
        return "\n".join([
            "[Interface]", f"PrivateKey = {client_private}", f"Address = {vpn_ip}/32", "",
            "[Peer]", f"PublicKey = {server_public}", f"Endpoint = {endpoint}",
            f"AllowedIPs = {self.settings.network.with_prefixlen}",
            f"PersistentKeepalive = {self.settings.persistent_keepalive}", "",
        ])

    def revoke_device(self, device_id: str) -> dict | None:
        row = self.store.get(device_id)
        if not row:
            return None
        if row["status"] != "REVOKED":
            self.wireguard.remove_peer(row["public_key"])
            row = self.store.revoke(device_id) or row
            self.wireguard.write_config(self.store.list(active_only=True))
        return self.public_device(row)

    def restart(self) -> dict:
        self.wireguard.write_config(self.store.list(active_only=True))
        return self.wireguard.restart()

    def diagnostics(self) -> dict:
        endpoint = resolve_public_endpoint(self.settings)
        route = default_route()
        local_ipv4 = local_ipv4_for_default_route()
        external_ipv4, external_ipv4_error = upnp_external_ipv4()
        ipv6 = global_ipv6_addresses()
        external_ipv4_class = classify_external_ipv4(external_ipv4)
        nat_state = "UNKNOWN"
        if local_ipv4 and external_ipv4:
            nat_state = "CGNAT" if external_ipv4_class in {"CGNAT", "NON_PUBLIC"} else ("NAT" if local_ipv4 != external_ipv4 else "DIRECT")
        mapping = try_upnp_mapping(self.settings) if self.settings.auto_port_mapping else {"enabled": False, "attempted": False, "mapped": False, "error": None}
        try:
            wg_dump = self.wireguard.dump()
        except RuntimeError as exc:
            wg_dump = {"interface": None, "peers": [], "error": str(exc)}
        self.refresh_traffic()
        return {
            "wireguard_installed": self.wireguard.installed(),
            "wg_active": self.wireguard.interface_active() if self.wireguard.installed() else False,
            "interface": self.settings.interface, "server_ip": str(self.settings.server_ip),
            "wireguard_port": self.settings.listen_port, "backend_port": self.settings.backend_port,
            "backend_local_reachable": backend_port_open(self.settings.backend_port),
            "gateway": route.get("gateway"), "gateway_interface": route.get("interface"),
            "lan_ipv4": local_ipv4, "external_ipv4": external_ipv4,
            "external_ipv4_error": external_ipv4_error, "external_ipv4_class": external_ipv4_class,
            "global_ipv6": ipv6, "nat_state": nat_state,
            "public_endpoint": endpoint.endpoint, "public_host": endpoint.host,
            "endpoint_source": endpoint.source, "remote_state_code": endpoint.state_code,
            "remote_message": endpoint.message, "external_reachability_verified": endpoint.externally_verified,
            "port_mapping_capabilities": port_mapping_capabilities(),
            "port_mapping": mapping, "peers": wg_dump.get("peers", []),
        }
