from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INSTRUCTION_VERSION = "ge360-floorplan-agent-v1.0"
AUTONOMOUS_REPAIR_BUDGET = 0.30

_ROOT = Path(__file__).resolve().parent
_HANDBOOK = _ROOT / "instructions" / "handbook.md"
_CASES = _ROOT / "examples" / "geometry-cases.json"

_HINTS = {
    "rectangle-gap": ("gap", "close", "closure", "endpoint", "corner", "room"),
    "real-diagonal": ("diagonal", "angle", "orthogonal", "perpendicular"),
    "t-junction": ("intersection", "junction", "dangling", "divider", "split"),
    "shared-wall": ("shared", "multiple room", "two room", "three room"),
    "incompatible-measures": ("conflict", "incompatible", "mismatch", "length", "closure"),
    "opening-offset": ("opening", "door", "window", "offset", "width"),
}


def load_handbook() -> str:
    return _HANDBOOK.read_text(encoding="utf-8").strip()


def _all_examples() -> list[dict[str, Any]]:
    return json.loads(_CASES.read_text(encoding="utf-8"))


def select_examples(context: dict[str, Any] | None, max_examples: int = 4) -> list[dict[str, Any]]:
    examples = _all_examples()
    haystack = json.dumps(context or {}, ensure_ascii=False).lower()
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in examples:
        example_id = str(row.get("id"))
        score = sum(1 for hint in _HINTS.get(example_id, ()) if hint in haystack)
        ranked.append((score, example_id, row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [row for score, _, row in ranked if score > 0][:max_examples]
    if not selected:
        by_id = {str(row.get("id")): row for row in examples}
        selected = [by_id[x] for x in ("rectangle-gap", "real-diagonal") if x in by_id][:max_examples]
    return selected


def build_system_prompt(context: dict[str, Any] | None = None, max_examples: int = 4) -> str:
    examples = select_examples(context, max_examples=max_examples)
    return (
        f"# Instruction version: {INSTRUCTION_VERSION}\n\n"
        + load_handbook()
        + "\n\n# Esempi GE360 pertinenti al caso corrente\n"
        + json.dumps(examples, ensure_ascii=False, indent=2)
    )
