from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.config import Settings

_KEY_FILENAME = ".api-key"


def api_key_path(settings: Settings) -> Path:
    configured = os.getenv("GE360_API_KEY_FILE", "").strip()
    return Path(configured) if configured else settings.data_dir / _KEY_FILENAME


def read_runtime_api_key(settings: Settings) -> str:
    path = api_key_path(settings)
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    except OSError:
        pass
    return settings.api_key.strip()


def generate_runtime_api_key(settings: Settings) -> str:
    key = secrets.token_urlsafe(48)
    path = api_key_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(key + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _run(command: list[str], timeout: float = 2.5) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)


def tailscale_status() -> dict[str, Any]:
    exe = shutil.which("tailscale")
    if not exe:
        return {
            "installed": False,
            "running": False,
            "backendState": "NOT_INSTALLED",
            "dnsName": None,
            "ipv4": None,
            "ips": [],
            "error": "tailscale command not found",
        }

    code, stdout, stderr = _run([exe, "status", "--json"])
    if code != 0:
        return {
            "installed": True,
            "running": False,
            "backendState": "UNKNOWN",
            "dnsName": None,
            "ipv4": None,
            "ips": [],
            "error": stderr or f"tailscale status exited with {code}",
        }

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "installed": True,
            "running": False,
            "backendState": "UNKNOWN",
            "dnsName": None,
            "ipv4": None,
            "ips": [],
            "error": "tailscale status returned invalid JSON",
        }

    state = str(payload.get("BackendState") or "UNKNOWN")
    self_node = payload.get("Self") if isinstance(payload.get("Self"), dict) else {}
    dns = str(self_node.get("DNSName") or "").rstrip(".") or None
    ips = [str(value) for value in (self_node.get("TailscaleIPs") or [])]
    ipv4 = next((value for value in ips if "." in value), None)

    return {
        "installed": True,
        "running": state.lower() == "running",
        "backendState": state,
        "dnsName": dns,
        "ipv4": ipv4,
        "ips": ips,
        "error": None,
    }


def tailscale_serve_status() -> dict[str, Any]:
    exe = shutil.which("tailscale")
    if not exe:
        return {"configured": False, "urls": [], "error": "tailscale command not found"}

    code, stdout, stderr = _run([exe, "serve", "status"])
    if code != 0:
        return {"configured": False, "urls": [], "error": stderr or f"tailscale serve status exited with {code}"}

    urls = sorted(set(re.findall(r"https://[^\s]+", stdout)))
    return {
        "configured": bool(urls),
        "urls": urls,
        "error": None,
    }


def connection_profile(settings: Settings) -> dict[str, Any]:
    status = tailscale_status()
    serve = tailscale_serve_status()
    dns = status.get("dnsName")
    suggested_root = f"https://{dns}" if status.get("running") and dns else None

    active_root = None
    if serve.get("urls"):
        active_root = str(serve["urls"][0]).rstrip("/")
    elif serve.get("configured"):
        active_root = suggested_root

    root = active_root or suggested_root
    return {
        "apiKeyConfigured": bool(read_runtime_api_key(settings)),
        "local": {
            "rootUrl": f"http://127.0.0.1:{settings.port}",
            "frontendServerUrl": f"http://127.0.0.1:{settings.port}/api/v1",
        },
        "tailscale": {
            **status,
            "serveConfigured": bool(serve.get("configured")),
            "serveUrls": serve.get("urls") or [],
            "serveError": serve.get("error"),
            "suggestedRootUrl": suggested_root,
            "frontendServerUrl": f"{root}/api/v1" if root else None,
        },
        "setupUrl": f"http://127.0.0.1:{settings.port}/setup/",
    }
