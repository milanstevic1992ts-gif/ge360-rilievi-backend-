from functools import lru_cache
from pathlib import Path
PROMPT_VERSION="cad-planner-v2-best-effort"
_PATH=Path(__file__).with_name("prompts")/"cad_planner_v1.txt"
@lru_cache(maxsize=1)
def load_cad_planner_prompt():return _PATH.read_text(encoding="utf-8").strip()
