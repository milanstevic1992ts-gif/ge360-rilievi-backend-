from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from threading import RLock
from typing import Callable

from .config import BridgeSettings

Runner = Callable[[list[str], str | None, float], tuple[int, str, str]]
MANAGED_MARKER = "# Managed by GE360 DIRECT BRIDGE"


def run_command(args: list[str], input_text: str | None = None, timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            args, input=input_text, capture_output=True, text=True, check=False, timeout=timeout
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def parse_wg_dump(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return {"interface": None, "peers": []}
    head = lines[0].split("\t")
    interface = {
        "public_key": head[1] if len(head) > 1 else None,
        "listen_port": int(head[2]) if len(head) > 2 and head[2].isdigit() else None,
        "fwmark": head[3] if len(head) > 3 else None,
    }
    peers: list[dict] = []
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        try:
            handshake, rx, tx, keepalive = int(cols[4] or 0), int(cols[5] or 0), int(cols[6] or 0), int(cols[7] or 0)
        except ValueError:
            continue
        peers.append({
            "public_key": cols[0],
            "endpoint": None if cols[2] == "(none)" else cols[2],
            "allowed_ips": cols[3],
            "latest_handshake": handshake,
            "rx_bytes": rx,
            "tx_bytes": tx,
            "persistent_keepalive": keepalive,
        })
    return {"interface": interface, "peers": peers}


class WireGuardController:
    def __init__(self, settings: BridgeSettings, runner: Runner = run_command):
        self.settings = settings
        self.runner = runner
        self._lock = RLock()

    @staticmethod
    def _which(name: str) -> str | None:
        return shutil.which(name)

    def installed(self) -> bool:
        return bool(self._which("wg") and self._which("wg-quick"))

    def _exe(self, name: str) -> str:
        value = self._which(name)
        if not value:
            raise RuntimeError(f"{name} command not found")
        return value

    def generate_keypair(self) -> tuple[str, str]:
        wg = self._exe("wg")
        code, private, err = self.runner([wg, "genkey"], None, 4.0)
        if code != 0 or not private:
            raise RuntimeError(err or "wg genkey failed")
        code, public, err = self.runner([wg, "pubkey"], private + "\n", 4.0)
        if code != 0 or not public:
            raise RuntimeError(err or "wg pubkey failed")
        return private.strip(), public.strip()

    @staticmethod
    def _atomic_secret_write(path: Path, value: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
        tmp.write_text(value.strip() + "\n", encoding="utf-8")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        os.chmod(path, mode)

    def ensure_server_identity(self) -> tuple[str, str]:
        private_path, public_path = self.settings.server_private_key_path, self.settings.server_public_key_path
        self.settings.config_dir.mkdir(parents=True, exist_ok=True)
        if private_path.is_file() and private_path.read_text(encoding="utf-8").strip():
            private = private_path.read_text(encoding="utf-8").strip()
            if public_path.is_file() and public_path.read_text(encoding="utf-8").strip():
                return private, public_path.read_text(encoding="utf-8").strip()
            wg = self._exe("wg")
            code, public, err = self.runner([wg, "pubkey"], private + "\n", 4.0)
            if code != 0 or not public:
                raise RuntimeError(err or "wg pubkey failed")
            self._atomic_secret_write(public_path, public.strip(), 0o640)
            return private, public.strip()
        private, public = self.generate_keypair()
        self._atomic_secret_write(private_path, private, 0o640)
        self._atomic_secret_write(public_path, public, 0o640)
        return private, public

    def server_public_key(self) -> str:
        return self.ensure_server_identity()[1]

    def render_config(self, devices: list[dict]) -> str:
        private, _ = self.ensure_server_identity()
        lines = [MANAGED_MARKER, "[Interface]", f"Address = {self.settings.server_cidr}", f"ListenPort = {self.settings.listen_port}", f"PrivateKey = {private}", ""]
        for device in devices:
            if device.get("status") != "ACTIVE":
                continue
            lines.extend([f"# ge360-device-id={device['device_id']}", "[Peer]", f"PublicKey = {device['public_key']}", f"AllowedIPs = {device['vpn_ip']}/32", ""])
        return "\n".join(lines).rstrip() + "\n"

    def write_config(self, devices: list[dict]) -> None:
        path = self.settings.wg_config_path
        with self._lock:
            if path.exists() and MANAGED_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
                raise RuntimeError(f"Refusing to overwrite unmanaged WireGuard config: {path}")
            self._atomic_secret_write(path, self.render_config(devices), 0o640)

    def interface_active(self) -> bool:
        if not self.installed():
            return False
        code, _, _ = self.runner([self._exe("wg"), "show", self.settings.interface], None, 3.0)
        return code == 0

    def apply_peer(self, public_key: str, vpn_ip: str) -> None:
        if not self.interface_active():
            return
        code, _, err = self.runner([self._exe("wg"), "set", self.settings.interface, "peer", public_key, "allowed-ips", f"{vpn_ip}/32"], None, 4.0)
        if code != 0:
            raise RuntimeError(err or "wg set peer failed")

    def remove_peer(self, public_key: str) -> None:
        if not self.interface_active():
            return
        code, _, err = self.runner([self._exe("wg"), "set", self.settings.interface, "peer", public_key, "remove"], None, 4.0)
        if code != 0:
            raise RuntimeError(err or "wg peer remove failed")

    def restart(self) -> dict:
        quick = self._exe("wg-quick")
        with self._lock:
            down_code, _, down_err = self.runner([quick, "down", self.settings.interface], None, 10.0)
            up_code, _, up_err = self.runner([quick, "up", self.settings.interface], None, 10.0)
        if up_code != 0:
            raise RuntimeError(up_err or "wg-quick up failed")
        return {"ok": True, "downExitCode": down_code, "downError": down_err or None}

    def dump(self) -> dict:
        if not self.interface_active():
            return {"interface": None, "peers": []}
        code, out, err = self.runner([self._exe("wg"), "show", self.settings.interface, "dump"], None, 4.0)
        if code != 0:
            raise RuntimeError(err or "wg show dump failed")
        return parse_wg_dump(out)
