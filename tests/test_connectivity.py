from __future__ import annotations

import os
from pathlib import Path

from backend.config import Settings
from backend import connectivity


def cfg(tmp_path: Path) -> Settings:
    return Settings(
        "", tmp_path / "data", tmp_path / "data/db.sqlite3", "127.0.0.1", 8796,
        120, 2700, 250, 25, .5, False,
        "http://127.0.0.1:11434", "qwen3:8b", .1,
    )


def test_generated_runtime_key_is_persistent_and_private(tmp_path: Path):
    settings = cfg(tmp_path)
    key = connectivity.generate_runtime_api_key(settings)
    path = connectivity.api_key_path(settings)
    assert len(key) >= 48
    assert connectivity.read_runtime_api_key(settings) == key
    assert path.exists()
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600


def test_env_key_is_fallback_when_key_file_missing(tmp_path: Path):
    settings = cfg(tmp_path)
    settings = Settings(
        "env-key", settings.data_dir, settings.db_path, settings.host, settings.port,
        settings.default_wall_thickness_mm, settings.default_wall_height_mm,
        settings.snap_tolerance_mm, settings.orthogonal_tolerance_deg,
        settings.length_tolerance_mm, settings.ai_enabled, settings.ollama_url,
        settings.ollama_model, settings.ollama_timeout,
    )
    assert connectivity.read_runtime_api_key(settings) == "env-key"


def test_connection_profile_builds_frontend_tailscale_url(tmp_path: Path, monkeypatch):
    settings = cfg(tmp_path)
    monkeypatch.setattr(connectivity, "tailscale_status", lambda: {
        "installed": True, "running": True, "backendState": "Running",
        "dnsName": "jarvis.example.ts.net", "ipv4": "100.64.0.1",
        "ips": ["100.64.0.1"], "error": None,
    })
    monkeypatch.setattr(connectivity, "tailscale_serve_status", lambda: {
        "configured": True, "urls": ["https://jarvis.example.ts.net"], "error": None,
    })
    profile = connectivity.connection_profile(settings)
    assert profile["tailscale"]["frontendServerUrl"] == "https://jarvis.example.ts.net/api/v1"
    assert profile["local"]["frontendServerUrl"] == "http://127.0.0.1:8796/api/v1"
