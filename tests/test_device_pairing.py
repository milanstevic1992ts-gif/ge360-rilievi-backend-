from __future__ import annotations

import base64
import ipaddress
import json
import sqlite3
from pathlib import Path

from backend.bridge.config import BridgeSettings
from backend.bridge.manager import DirectBridgeManager
from backend.bridge.network import PublicEndpoint
from backend.bridge.qr import PAIRING_FORMAT, ge360_pairing_text
from backend.bridge.store import BridgeStore

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

class FakeWireGuard:
    def __init__(self):
        self.removed = []
    def installed(self): return True
    def interface_active(self): return True
    def generate_keypair(self): return "phone-private", "phone-public"
    def server_public_key(self): return "server-public"
    def write_config(self, devices): pass
    def apply_peer(self, public_key, vpn_ip): pass
    def remove_peer(self, public_key): self.removed.append(public_key)
    def dump(self): return {"interface": {}, "peers": []}
    def restart(self): return {"ok": True}

def endpoint():
    return PublicEndpoint(True, "vpn.example.test:51820", "vpn.example.test", "configured", "ENDPOINT_CONFIGURED")

def test_existing_bridge_database_migrates_token_columns(tmp_path: Path):
    path = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE bridge_devices (
      device_id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      vpn_ip TEXT NOT NULL UNIQUE,
      public_key TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      last_seen_at TEXT,
      status TEXT NOT NULL,
      revoked_at TEXT,
      last_handshake_at TEXT,
      rx_bytes INTEGER NOT NULL DEFAULT 0,
      tx_bytes INTEGER NOT NULL DEFAULT 0
    );
    """)
    con.close()
    BridgeStore(path)
    con = sqlite3.connect(path)
    columns = {row[1] for row in con.execute("PRAGMA table_info(bridge_devices)")}
    con.close()
    assert "app_token_hash" in columns
    assert "app_token_created_at" in columns

def test_device_token_is_hashed_and_revoked(tmp_path: Path):
    s = settings(tmp_path)
    store = BridgeStore(s.db_path)
    device = store.allocate_and_add("Telefono", "pub-a", s.network, s.server_ip)
    token = store.issue_app_token(device["device_id"])
    assert token.startswith("ge360d_")
    assert store.authenticate_app_token(token)["device_id"] == device["device_id"]
    assert token.encode() not in s.db_path.read_bytes()
    store.revoke(device["device_id"])
    assert store.authenticate_app_token(token) is None

def test_ge360_pairing_envelope_is_frontend_ready():
    raw = ge360_pairing_text(
        wireguard_config="[Interface]\nPrivateKey = phone-private\n\n[Peer]\nPublicKey = server\nEndpoint = vpn.example.test:51820\nAllowedIPs = 10.88.0.0/24\n",
        backend_url="http://10.88.0.1:9888",
        api_key="ge360d_device-secret",
        device_id="device-1",
    )
    payload = json.loads(raw)
    assert payload["format"] == PAIRING_FORMAT
    assert payload["version"] == 1
    assert payload["api_key"] == "ge360d_device-secret"
    assert payload["backend_url"] == "http://10.88.0.1:9888"
    assert payload["pairing"]["backend_url"] == "http://10.88.0.1:9888"
    assert "phone-private" in payload["pairing"]["wireguard_config"]

def test_manager_pairing_qr_contains_device_token_not_master(tmp_path: Path, monkeypatch):
    from backend.bridge import manager as manager_module
    s = settings(tmp_path)
    manager = DirectBridgeManager(s, store=BridgeStore(s.db_path), wireguard=FakeWireGuard())
    monkeypatch.setattr(manager_module, "resolve_public_endpoint", lambda _s: endpoint())
    monkeypatch.setattr(manager_module, "try_upnp_mapping", lambda _s: {"enabled": False, "attempted": False, "mapped": False, "error": None})
    created = manager.create_device("Telefono Milan")
    token = created["pairing"]["api_key"]
    assert token.startswith("ge360d_")
    assert created["pairing"]["auth_scope"] == "device"
    assert created["pairing"]["format"] == PAIRING_FORMAT
    assert manager.authenticate_app_token(token)
    assert token.encode() not in s.db_path.read_bytes()
    assert base64.b64decode(created["pairing"]["qr_png_base64"]).startswith(b"\x89PNG")
    assert base64.b64decode(created["pairing"]["wireguard_qr_png_base64"]).startswith(b"\x89PNG")
    manager.revoke_device(created["device"]["device_id"])
    assert not manager.authenticate_app_token(token)

def test_device_token_can_use_app_api_but_not_setup(tmp_path: Path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient

    monkeypatch.setenv("GE360_API_KEY", "master-key")
    monkeypatch.setenv("GE360_API_KEY_FILE", str(tmp_path / "missing-master-file"))
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path / "api"))
    monkeypatch.setenv("GE360_DB_PATH", str(tmp_path / "api" / "db.sqlite3"))
    monkeypatch.setenv("GE360_AI_ENABLED", "false")
    monkeypatch.setenv("GE360_BRIDGE_STATE_DIR", str(tmp_path / "bridge"))
    monkeypatch.setenv("GE360_BRIDGE_CONFIG_DIR", str(tmp_path / "bridge-config"))
    monkeypatch.setenv("GE360_BRIDGE_WG_CONFIG", str(tmp_path / "bridge-config" / "wg0.conf"))

    import backend.main as main
    main = importlib.reload(main)

    class FakeBridgeAuth:
        def authenticate_app_token(self, token: str) -> bool:
            return token == "ge360d_valid-device-token-abcdefghijklmnopqrstuvwxyz"

    main._bridge_manager = FakeBridgeAuth()
    monkeypatch.setattr(main, "connection_profile", lambda _settings: {"ok": True})
    client = TestClient(main.app, client=("10.88.0.2", 50000))
    token = "ge360d_valid-device-token-abcdefghijklmnopqrstuvwxyz"

    app_api = client.get("/api/v1/health", headers={"X-GE360-API-Key": token, "host": "10.88.0.1"})
    assert app_api.status_code == 200

    setup_api = client.get("/api/v1/setup/status", headers={"X-GE360-API-Key": token, "host": "10.88.0.1"})
    assert setup_api.status_code == 403

    master_setup = client.get("/api/v1/setup/status", headers={"X-GE360-API-Key": "master-key", "host": "10.88.0.1"})
    assert master_setup.status_code == 200
