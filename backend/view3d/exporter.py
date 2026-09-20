from __future__ import annotations

from pathlib import Path

from backend.models import PlanModel
from backend.view3d.builder import build_scene


def export_glb(model: PlanModel, path: Path) -> tuple[bool, str | None]:
    try:
        scene = build_scene(model)
        data = scene.export(file_type="glb")
        path.write_bytes(data)
        return True, None
    except Exception as exc:
        return False, str(exc)
