from __future__ import annotations

import ipaddress
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

SCHEMA = """
CREATE TABLE IF NOT EXISTS bridge_devices (
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
CREATE INDEX IF NOT EXISTS idx_bridge_devices_status ON bridge_devices(status);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BridgeStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self.connect() as con:
            con.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row else None

    def allocate_and_add(self, name: str, public_key: str, network: ipaddress.IPv4Network, server_ip: ipaddress.IPv4Address) -> dict:
        with self._lock, self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            used = {ipaddress.ip_address(row[0]) for row in con.execute("SELECT vpn_ip FROM bridge_devices")}
            chosen = next((candidate for candidate in network.hosts() if candidate != server_ip and candidate not in used), None)
            if chosen is None:
                raise RuntimeError("GE360_DIRECT_BRIDGE_ADDRESS_POOL_EXHAUSTED")
            device_id = str(uuid.uuid4())
            created_at = _utcnow()
            try:
                con.execute(
                    "INSERT INTO bridge_devices(device_id,name,vpn_ip,public_key,created_at,status) VALUES(?,?,?,?,?,?)",
                    (device_id, name, str(chosen), public_key, created_at, "ACTIVE"),
                )
                con.commit()
            except sqlite3.IntegrityError as exc:
                con.rollback()
                raise ValueError("Duplicate WireGuard public key or VPN IP") from exc
        return self.get(device_id) or {}

    def get(self, device_id: str) -> dict | None:
        with self.connect() as con:
            return self._row(con.execute("SELECT * FROM bridge_devices WHERE device_id=?", (device_id,)).fetchone())

    def list(self, *, active_only: bool = False) -> list[dict]:
        query = "SELECT * FROM bridge_devices"
        params: tuple[str, ...] = ()
        if active_only:
            query += " WHERE status=?"
            params = ("ACTIVE",)
        query += " ORDER BY created_at ASC"
        with self.connect() as con:
            return [dict(row) for row in con.execute(query, params).fetchall()]

    def revoke(self, device_id: str) -> dict | None:
        now = _utcnow()
        with self._lock, self.connect() as con:
            row = con.execute("SELECT * FROM bridge_devices WHERE device_id=?", (device_id,)).fetchone()
            if not row:
                return None
            con.execute("UPDATE bridge_devices SET status='REVOKED', revoked_at=? WHERE device_id=?", (now, device_id))
            con.commit()
        return self.get(device_id)

    def update_traffic(self, public_key: str, *, handshake_epoch: int, rx_bytes: int, tx_bytes: int) -> None:
        handshake = None
        last_seen = None
        if handshake_epoch > 0:
            handshake = datetime.fromtimestamp(handshake_epoch, tz=timezone.utc).isoformat()
            last_seen = handshake
        with self.connect() as con:
            con.execute(
                "UPDATE bridge_devices SET last_handshake_at=?, last_seen_at=COALESCE(?,last_seen_at), rx_bytes=?, tx_bytes=? WHERE public_key=?",
                (handshake, last_seen, max(0, rx_bytes), max(0, tx_bytes), public_key),
            )
            con.commit()
