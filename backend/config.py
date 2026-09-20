from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


@dataclass(frozen=True)
class Settings:
    api_key: str
    data_dir: Path
    db_path: Path
    host: str
    port: int
    default_wall_thickness_mm: float
    default_wall_height_mm: float
    snap_tolerance_mm: float
    orthogonal_tolerance_deg: float
    length_tolerance_mm: float
    ai_enabled: bool
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    cors_origins: tuple[str, ...] = (
        "http://localhost",
        "http://127.0.0.1",
        "https://localhost",
        "capacitor://localhost",
    )
    job_workers: int = 2


def get_settings() -> Settings:
    data_dir = Path(os.getenv("GE360_DATA_DIR", "/opt/ge360/data/rilievi"))
    return Settings(
        api_key=os.getenv("GE360_API_KEY", os.getenv("GE360_RILIEVO_API_KEY", "")),
        data_dir=data_dir,
        db_path=Path(os.getenv("GE360_DB_PATH", str(data_dir / "ge360-rilievi.sqlite3"))),
        host=os.getenv("GE360_HOST", "127.0.0.1"),
        port=int(os.getenv("GE360_PORT", "8796")),
        default_wall_thickness_mm=float(os.getenv("GE360_DEFAULT_WALL_THICKNESS_MM", "120")),
        default_wall_height_mm=float(os.getenv("GE360_DEFAULT_WALL_HEIGHT_MM", "2700")),
        snap_tolerance_mm=float(os.getenv("GE360_SNAP_TOLERANCE_MM", "250")),
        orthogonal_tolerance_deg=float(os.getenv("GE360_ORTHOGONAL_TOLERANCE_DEG", "25")),
        length_tolerance_mm=float(os.getenv("GE360_LENGTH_TOLERANCE_MM", "0.5")),
        ai_enabled=_bool("GE360_AI_ENABLED", False),
        ollama_url=os.getenv("GE360_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        ollama_model=os.getenv("GE360_OLLAMA_MODEL", "qwen3:8b"),
        ollama_timeout=float(os.getenv("GE360_OLLAMA_TIMEOUT", "20")),
        cors_origins=_csv(
            "GE360_CORS_ORIGINS",
            ("http://localhost", "http://127.0.0.1", "https://localhost", "capacitor://localhost"),
        ),
        job_workers=max(1, int(os.getenv("GE360_JOB_WORKERS", "2"))),
    )
