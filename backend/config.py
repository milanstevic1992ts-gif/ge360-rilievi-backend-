from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("GE360_DATA_DIR", "/opt/ge360/data/rilievi"))
    db_path: Path = Path(os.getenv("GE360_DB_PATH", "/opt/ge360/data/rilievi/ge360-rilievi.sqlite3"))
    api_key: str = os.getenv("GE360_API_KEY", os.getenv("GE360_RILIEVO_API_KEY", ""))
    host: str = os.getenv("GE360_HOST", "127.0.0.1")
    port: int = int(os.getenv("GE360_PORT", "8796"))
    wall_thickness_mm: float = float(os.getenv("GE360_DEFAULT_WALL_THICKNESS_MM", "120"))
    snap_tolerance_mm: float = float(os.getenv("GE360_SNAP_TOLERANCE_MM", "250"))
    axis_tolerance_deg: float = float(os.getenv("GE360_AXIS_TOLERANCE_DEG", "18"))
    length_tolerance_mm: float = float(os.getenv("GE360_LENGTH_TOLERANCE_MM", "0.05"))
    closure_tolerance_mm: float = float(os.getenv("GE360_CLOSURE_TOLERANCE_MM", "2.0"))
    ollama_url: str = os.getenv("GE360_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("GE360_OLLAMA_MODEL", "qwen2.5:7b")
    ollama_timeout: float = float(os.getenv("GE360_OLLAMA_TIMEOUT", "20"))
    agent_enabled: bool = _bool("GE360_AGENT_ENABLED", False)
    telegram_enabled: bool = _bool("GE360_TELEGRAM_ENABLED", False)
    telegram_bot_token: str = os.getenv("GE360_TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("GE360_TELEGRAM_CHAT_ID", "")
    public_base_url: str = os.getenv("GE360_PUBLIC_BASE_URL", "").rstrip("/")
    glb_enabled: bool = _bool("GE360_GLB_ENABLED", True)


def get_settings() -> Settings:
    return Settings()
