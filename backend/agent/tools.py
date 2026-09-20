from __future__ import annotations

import math
from typing import Any

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult


ALLOWED = {"make_parallel", "make_perpendicular", "align_wall"}


def _nearest_equivalent(angle: float, reference: float, period: float = math.pi) -> float:
    candidates = [reference + k * period for k in range(-3, 4)]
    return min(candidates, key=lambda a: abs((a-angle+math.pi)%(2*math.pi)-math.pi))


def operation_to_angle_override(operation: dict[str, Any], plan: NormalizedPlan, solved: SolverResult) -> tuple[dict[str, float] | None, str]:
    op_type = operation.get("type")
    wall_ids = {w.id for w in plan.walls}
    if op_type not in ALLOWED:
        return None, "unsupported operation"
    if float(operation.get("confidence", 0)) < 0.65:
        return None, "confidence below safety threshold"

    if op_type in {"make_parallel", "make_perpendicular"}:
        a, b = operation.get("wallA"), operation.get("wallB")
        if a not in wall_ids or b not in wall_ids or a == b:
            return None, "invalid wall references"
        angle_a = math.radians(solved.wall_meta[a]["solvedAngleDeg"])
        angle_b = math.radians(solved.wall_meta[b]["solvedAngleDeg"])
        target = angle_a if op_type == "make_parallel" else angle_a + math.pi/2
        return {b: _nearest_equivalent(angle_b, target)}, "ok"

    wall_id = operation.get("wallId")
    if wall_id not in wall_ids:
        return None, "invalid wallId"
    angle_deg = operation.get("angleDeg")
    if angle_deg is None:
        return None, "missing angleDeg"
    current = math.radians(solved.wall_meta[wall_id]["solvedAngleDeg"])
    target = math.radians(float(angle_deg))
    if abs((target-current+math.pi)%(2*math.pi)-math.pi) > math.radians(30):
        return None, "requested rotation is too large"
    return {wall_id: target}, "ok"
