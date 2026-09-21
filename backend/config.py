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
    # --- Rilievo fedele (solver v2) ---
    accept_abs_mm: float = 10.0          # scarto accettato per lato: max(accept_abs_mm, accept_rel * L)
    accept_rel: float = 0.005
    measure_sigma_mm: float = 5.0        # incertezza tipica di una misura laser/metro
    auto_close_mm: float = 600.0         # chiusura automatica di varchi nello schizzo
    diagonal_snap_deg: float = 12.0      # aggancio pareti a 45° (smussi)
    bath_tiling_height_mm: float = 2200.0
    require_api_key: bool = True
    mc_samples: int = 40                 # simulazioni Monte Carlo per gli intervalli dei m²
    learn_errors: bool = True            # il modello degli errori impara dai rilievi reali


def get_settings() -> Settings:
    data_dir = Path(os.getenv("GE360_DATA_DIR", "/opt/ge360/data/rilievi"))
    return Settings(
        api_key=os.getenv("GE360_API_KEY", os.getenv("GE360_RILIEVO_API_KEY", "")),
        data_dir=data_dir,
        db_path=Path(os.getenv("GE360_DB_PATH", str(data_dir / "ge360-rilievi.sqlite3"))),
        host=os.getenv("GE360_HOST", "127.0.0.1"),
        port=int(os.getenv("GE360_PORT", "9888")),
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
        accept_abs_mm=float(os.getenv("GE360_ACCEPT_ABS_MM", "10")),
        accept_rel=float(os.getenv("GE360_ACCEPT_REL", "0.005")),
        measure_sigma_mm=float(os.getenv("GE360_MEASURE_SIGMA_MM", "5")),
        auto_close_mm=float(os.getenv("GE360_AUTO_CLOSE_MM", "600")),
        diagonal_snap_deg=float(os.getenv("GE360_DIAGONAL_SNAP_DEG", "12")),
        bath_tiling_height_mm=float(os.getenv("GE360_BATH_TILING_HEIGHT_MM", "2200")),
        require_api_key=_bool("GE360_REQUIRE_API_KEY", True),
        mc_samples=min(200, max(0, int(os.getenv("GE360_MC_SAMPLES", "40")))),
        learn_errors=os.getenv("GE360_LEARN_ERRORS", "true").strip().lower() in {"1", "true", "yes", "on"},
    )
