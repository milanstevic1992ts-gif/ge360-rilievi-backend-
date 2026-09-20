from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
LOCKED_AI_MODEL="qwen3:8b";LOCKED_AI_PROVIDER="ollama"
def _bool(name,default=False):
    raw=os.getenv(name);return default if raw is None else raw.strip().lower() in {"1","true","yes","on"}
def _csv(name,default):
    raw=os.getenv(name);vals=tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else ();return vals or default
@dataclass(frozen=True)
class Settings:
    api_key:str;data_dir:Path;db_path:Path;host:str;port:int;default_wall_thickness_mm:float;default_wall_height_mm:float;snap_tolerance_mm:float;orthogonal_tolerance_deg:float;length_tolerance_mm:float;ai_enabled:bool;ollama_url:str;ollama_model:str;ollama_timeout:float
    cors_origins:tuple[str,...]=("http://localhost","http://127.0.0.1","https://localhost","capacitor://localhost");job_workers:int=2;ai_provider:str=LOCKED_AI_PROVIDER;ai_base_url:str="http://127.0.0.1:11434/v1";ai_max_tool_rounds:int=4;ai_best_effort:bool=True;ai_critic_enabled:bool=True;ai_memory_enabled:bool=True;ai_max_strategies:int=3
    @property
    def ai_model(self):return LOCKED_AI_MODEL
    @property
    def ai_timeout_seconds(self):return self.ollama_timeout
def get_settings():
    d=Path(os.getenv("GE360_DATA_DIR","/opt/ge360/data/rilievi"));provider=os.getenv("GE360_AI_PROVIDER",LOCKED_AI_PROVIDER).lower();model=os.getenv("GE360_AI_MODEL",LOCKED_AI_MODEL)
    if provider!=LOCKED_AI_PROVIDER:raise ValueError("GE360_AI_PROVIDER locked to ollama")
    if model!=LOCKED_AI_MODEL:raise ValueError("GE360_AI_MODEL locked to qwen3:8b")
    base=os.getenv("GE360_AI_BASE_URL","http://127.0.0.1:11434/v1").rstrip("/");root=os.getenv("GE360_OLLAMA_URL",base[:-3] if base.endswith("/v1") else "http://127.0.0.1:11434").rstrip("/")
    return Settings(api_key=os.getenv("GE360_API_KEY",os.getenv("GE360_RILIEVO_API_KEY","")),data_dir=d,db_path=Path(os.getenv("GE360_DB_PATH",str(d/"ge360-rilievi.sqlite3"))),host=os.getenv("GE360_HOST","127.0.0.1"),port=int(os.getenv("GE360_PORT","9888")),default_wall_thickness_mm=float(os.getenv("GE360_DEFAULT_WALL_THICKNESS_MM","120")),default_wall_height_mm=float(os.getenv("GE360_DEFAULT_WALL_HEIGHT_MM","2700")),snap_tolerance_mm=float(os.getenv("GE360_SNAP_TOLERANCE_MM","250")),orthogonal_tolerance_deg=float(os.getenv("GE360_ORTHOGONAL_TOLERANCE_DEG","25")),length_tolerance_mm=float(os.getenv("GE360_LENGTH_TOLERANCE_MM","0.5")),ai_enabled=_bool("GE360_AI_ENABLED",True),ollama_url=root,ollama_model=LOCKED_AI_MODEL,ollama_timeout=max(5,float(os.getenv("GE360_AI_TIMEOUT_SECONDS","45"))),cors_origins=_csv("GE360_CORS_ORIGINS",("http://localhost","http://127.0.0.1","https://localhost","capacitor://localhost")),job_workers=max(1,int(os.getenv("GE360_JOB_WORKERS","2"))),ai_provider=LOCKED_AI_PROVIDER,ai_base_url=base,ai_max_tool_rounds=max(1,min(int(os.getenv("GE360_AI_MAX_TOOL_ROUNDS","4")),8)),ai_best_effort=_bool("GE360_AI_BEST_EFFORT",True),ai_critic_enabled=_bool("GE360_AI_CRITIC_ENABLED",True),ai_memory_enabled=_bool("GE360_AI_MEMORY_ENABLED",True),ai_max_strategies=max(1,min(int(os.getenv("GE360_AI_MAX_STRATEGIES","3")),3)))
