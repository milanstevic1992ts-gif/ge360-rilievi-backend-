from __future__ import annotations

import base64
import ipaddress
from pathlib import Path

import pytest

from backend.bridge.config import BridgeSettings
from backend.bridge.manager import DirectBridgeManager
from backend.bridge.network import PublicEndpoint, classify_external_ipv4, format_endpoint, resolve_public_endpoint
from backend.bridge.qr import wireguard_qr_png_base64
from backend.bridge.store import BridgeStore
from backend.bridge.wireguard import MANAGED_MARKER, WireGuardController, parse_wg_dump


def settings(tmp_path: Path) -> BridgeSettings:
    config = tmp_path / "etc"
    state = tmp_path / "state"
    return BridgeSettings(
        enabled=True,
        interface="wg0",
        network=ipaddress.ip_network("10.88.0.0/24"),
        server_ip=ipaddress.ip_address("10.88.0.1"),
        listen_port=51820,
        backend_port=9888,
        public_host="vpn.example.test",
        config_dir=config,
        state_dir=state,
        wg_config_path=tmp_path / "wireguard" / "wg0.conf",
        server_private_key_path=config / "server.key",
        server_public_key_path=config / "server.pub",
        db_path=state / "bridge.sqlite3",
    )


def test_ip_allocation_is_stable_unique_and_does_not_reuse_revoked_ip(tmp_path: Path):
    s = settings(tmp_path)
    store = BridgeStore(s.db_path)
    first = store.allocate_and_add("Telefono", "pub-a", s.network, s.server_ip)
    second = store.allocate_and_add("Tablet", "pub-b", s.network, s.server_ip)
    assert first["vpn_ip"] == "10.88.0.2"
    assert second["vpn_ip"] == "10.88.0.3"
    store.revoke(first["device_id"])
    third = store.allocate_and_add("Secondario", "pub-c", s.network, s.server_ip)
    assert third["vpn_ip"] == "10.88.0.4"


def test_duplicate_public_key_is_rejected(tmp_path: Path):
    s = settings(tmp_path)
    store = BridgeStore(s.db_path)
    store.allocate_and_add("Telefono", "same-key", s.network, s.server_ip)
    with pytest.raises(ValueError):
        store.allocate_and_add("Tablet", "same-key", s.network, s.server_ip)


def test_store_persists_across_instances(tmp_path: Path):
    s = settings(tmp_path)
    first = BridgeStore(s.db_path)
    created = first.allocate_and_add("Telefono", "pub-a", s.network, s.server_ip)
    second = BridgeStore(s.db_path)
    assert second.get(created["device_id"])["vpn_ip"] == "10.88.0.2"


def test_qr_contains_png_bytes():
    encoded = wireguard_qr_png_base64("[Interface]\nPrivateKey = secret\n")
    raw = base64.b64decode(encoded)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")


def test_cgnat_detection_logic():
    assert classify_external_ipv4("100.64.12.9") == "CGNAT"
    assert classify_external_ipv4("10.1.2.3") == "NON_PUBLIC"
    assert classify_external_ipv4("8.8.8.8") == "PUBLIC"
    assert format_endpoint("2001:4860:4860::8888", 51820) == "[2001:4860:4860::8888]:51820"


def test_configured_hostname_is_rejected_when_router_reports_cgnat(tmp_path: Path, monkeypatch):
    from backend.bridge import network as network_module

    s = settings(tmp_path)
    monkeypatch.setattr(network_module.shutil, "which", lambda name: "/usr/bin/upnpc" if name == "upnpc" else None)

    def runner(args, input_text, timeout):
        assert args[:2] == ["/usr/bin/upnpc", "-s"]
        return 0, "ExternalIPAddress = 100.64.12.9", ""

    endpoint = resolve_public_endpoint(s, runner)
    assert endpoint.available is False
    assert endpoint.state_code == "REMOTE_ACCESS_UNAVAILABLE_CGNAT"


def test_parse_wg_dump():
    dump = (
        "priv\tserverpub\t51820\toff\n"
        "peerpub\t(none)\t198.51.100.3:40000\t10.88.0.2/32\t1700000000\t123\t456\t25\n"
    )
    parsed = parse_wg_dump(dump)
    assert parsed["interface"]["public_key"] == "serverpub"
    assert parsed["interface"]["listen_port"] == 51820
    assert parsed["peers"][0]["rx_bytes"] == 123
    assert parsed["peers"][0]["tx_bytes"] == 456


def test_wireguard_config_has_managed_marker_and_peer(tmp_path: Path, monkeypatch):
    s = settings(tmp_path)
    controller = WireGuardController(s)
    monkeypatch.setattr(controller, "ensure_server_identity", lambda: ("server-private", "server-public"))
    content = controller.render_config([
        {"device_id": "d1", "status": "ACTIVE", "public_key": "peer-pub", "vpn_ip": "10.88.0.2"}
    ])
    assert MANAGED_MARKER in content
    assert "Address = 10.88.0.1/24" in content
    assert "ListenPort = 51820" in content
    assert "AllowedIPs = 10.88.0.2/32" in content


def test_unmanaged_wg_config_is_never_overwritten(tmp_path: Path, monkeypatch):
    s = settings(tmp_path)
    s.wg_config_path.parent.mkdir(parents=True)
    s.wg_config_path.write_text("[Interface]\nPrivateKey = external\n", encoding="utf-8")
    controller = WireGuardController(s)
    monkeypatch.setattr(controller, "ensure_server_identity", lambda: ("server-private", "server-public"))
    with pytest.raises(RuntimeError, match="unmanaged"):
        controller.write_config([])


class FakeWireGuard:
    def __init__(self, s: BridgeSettings):
        self.settings = s
        self.removed = []
        self.applied = []
        self.written = []
        self.n = 0
        self.restarts = 0

    def installed(self): return True
    def interface_active(self): return True
    def generate_keypair(self):
        self.n += 1
        return f"private-{self.n}", f"public-{self.n}"
    def server_public_key(self): return "server-public"
    def write_config(self, devices): self.written = list(devices)
    def apply_peer(self, public_key, vpn_ip): self.applied.append((public_key, vpn_ip))
    def remove_peer(self, public_key): self.removed.append(public_key)
    def dump(self): return {"interface": {"listen_port": 51820}, "peers": []}
    def restart(self):
        self.restarts += 1
        return {"ok": True}


def endpoint():
    return PublicEndpoint(True, "vpn.example.test:51820", "vpn.example.test", "configured", "ENDPOINT_CONFIGURED")


def test_create_and_revoke_device_without_persisting_private_key(tmp_path: Path, monkeypatch):
    from backend.bridge import manager as manager_module

    s = settings(tmp_path)
    store = BridgeStore(s.db_path)
    wg = FakeWireGuard(s)
    manager = DirectBridgeManager(s, store=store, wireguard=wg)
    monkeypatch.setattr(manager_module, "resolve_public_endpoint", lambda _s: endpoint())
    monkeypatch.setattr(manager_module, "try_upnp_mapping", lambda _s: {"enabled": False, "attempted": False, "mapped": False, "error": None})

    created = manager.create_device("Telefono Milan")
    assert created["device"]["vpn_ip"] == "10.88.0.2"
    assert "PrivateKey = private-1" in created["pairing"]["wireguard_config"]
    assert b"private-1" not in s.db_path.read_bytes()
    assert wg.applied == [("public-1", "10.88.0.2")]

    revoked = manager.revoke_device(created["device"]["device_id"])
    assert revoked["status"] == "REVOKED"
    assert wg.removed == ["public-1"]
    assert store.list(active_only=True) == []


def test_bridge_health_online_when_wg_and_endpoint_are_available(tmp_path: Path, monkeypatch):
    from backend.bridge import manager as manager_module

    s = settings(tmp_path)
    manager = DirectBridgeManager(s, store=BridgeStore(s.db_path), wireguard=FakeWireGuard(s))
    monkeypatch.setattr(manager_module, "resolve_public_endpoint", lambda _s: endpoint())
    status = manager.status()
    assert status["state_code"] == "ONLINE"
    assert status["server_ip"] == "10.88.0.1"
    assert status["backend_port"] == 9888


def test_restart_rewrites_persistent_config_before_cycling_interface(tmp_path: Path):
    s = settings(tmp_path)
    store = BridgeStore(s.db_path)
    store.allocate_and_add("Telefono", "pub-a", s.network, s.server_ip)
    wg = FakeWireGuard(s)
    manager = DirectBridgeManager(s, store=store, wireguard=wg)
    result = manager.restart()
    assert result == {"ok": True}
    assert len(wg.written) == 1
    assert wg.restarts == 1
