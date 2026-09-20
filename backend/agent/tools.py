from __future__ import annotations

import copy
import math
from typing import Any

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult
from backend.geometry.topology import build_topology

TOOL_NAMES = (
    "inspect_plan", "inspect_wall", "find_near_endpoints", "connect_corner", "merge_nodes",
    "make_parallel", "make_perpendicular", "align_collinear", "close_room",
    "validate_plan", "score_plan",
)
ANGLE_TOOLS = {"make_parallel", "make_perpendicular", "align_collinear"}
TOPOLOGY_TOOLS = {"connect_corner", "merge_nodes", "close_room"}


def _tool(operation: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = str(operation.get("tool") or operation.get("type") or "")
    args = operation.get("args") if isinstance(operation.get("args"), dict) else operation
    return name, args


def inspect_plan(plan: NormalizedPlan, solved: SolverResult) -> dict:
    return {
        "planId": plan.plan_id,
        "walls": [
            {
                "id": w.id,
                "startNode": w.start_node,
                "endNode": w.end_node,
                "declaredLengthMm": w.length_mm,
                "solvedAngleDeg": solved.wall_meta[w.id]["solvedAngleDeg"],
                "lengthErrorMm": solved.wall_meta[w.id]["lengthErrorMm"],
            }
            for w in plan.walls
        ],
        "openings": [
            {k: o.get(k) for k in ("id", "type", "wallId", "widthCm", "offsetCm", "referenceEnd")}
            for o in plan.openings
        ],
    }


def inspect_wall(plan: NormalizedPlan, solved: SolverResult, wall_id: str) -> dict | None:
    wall = next((w for w in plan.walls if w.id == wall_id), None)
    if wall is None:
        return None
    return {
        "id": wall.id,
        "startNode": wall.start_node,
        "endNode": wall.end_node,
        "declaredLengthMm": wall.length_mm,
        **solved.wall_meta[wall.id],
    }


def find_near_endpoints(plan: NormalizedPlan, max_gap_mm: float = 500.0) -> list[dict]:
    nodes = list(plan.nodes.values())
    found = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            gap = math.hypot(a.sketch_x - b.sketch_x, a.sketch_y - b.sketch_y) * plan.scale_mm_per_unit
            if 0 < gap <= max_gap_mm:
                found.append({"nodeA": a.id, "nodeB": b.id, "gapMm": round(gap, 3)})
    return sorted(found, key=lambda row: row["gapMm"])


def _nearest_equivalent(angle: float, reference: float, period: float = math.pi) -> float:
    candidates = [reference + k * period for k in range(-3, 4)]
    return min(candidates, key=lambda a: abs((a - angle + math.pi) % (2 * math.pi) - math.pi))


def operation_to_angle_override(operation: dict[str, Any], plan: NormalizedPlan, solved: SolverResult) -> tuple[dict[str, float] | None, str]:
    name, args = _tool(operation)
    wall_ids = {w.id for w in plan.walls}
    if name not in ANGLE_TOOLS:
        return None, "not an angle tool"
    if float(operation.get("confidence", 0)) < 0.65:
        return None, "confidence below safety threshold"
    a, b = args.get("wallA"), args.get("wallB")
    if a not in wall_ids or b not in wall_ids or a == b:
        return None, "invalid wall references"
    angle_a = math.radians(solved.wall_meta[a]["solvedAngleDeg"])
    angle_b = math.radians(solved.wall_meta[b]["solvedAngleDeg"])
    target = angle_a if name in {"make_parallel", "align_collinear"} else angle_a + math.pi / 2
    return {b: _nearest_equivalent(angle_b, target)}, "ok"


def _merge_nodes(plan: NormalizedPlan, keep: str, drop: str, max_gap_mm: float) -> tuple[NormalizedPlan | None, str]:
    if keep == drop or keep not in plan.nodes or drop not in plan.nodes:
        return None, "invalid node references"
    a, b = plan.nodes[keep], plan.nodes[drop]
    gap = math.hypot(a.sketch_x - b.sketch_x, a.sketch_y - b.sketch_y) * plan.scale_mm_per_unit
    if gap > max_gap_mm:
        return None, f"node gap {gap:.1f} mm exceeds safety limit"
    candidate = copy.deepcopy(plan)
    ca, cb = candidate.nodes[keep], candidate.nodes[drop]
    ca.sketch_x = (ca.sketch_x + cb.sketch_x) / 2
    ca.sketch_y = (ca.sketch_y + cb.sketch_y) / 2
    ca.source_endpoints.extend(cb.source_endpoints)
    for wall in candidate.walls:
        if wall.start_node == drop:
            wall.start_node = keep
        if wall.end_node == drop:
            wall.end_node = keep
        if wall.start_node == wall.end_node:
            return None, f"merge would collapse wall {wall.id}"
    del candidate.nodes[drop]
    return candidate, "ok"


def apply_topology_operation(operation: dict[str, Any], plan: NormalizedPlan, max_gap_mm: float = 300.0) -> tuple[NormalizedPlan | None, str]:
    name, args = _tool(operation)
    if name not in TOPOLOGY_TOOLS:
        return None, "not a topology tool"
    if float(operation.get("confidence", 0)) < 0.65:
        return None, "confidence below safety threshold"
    if name == "merge_nodes":
        return _merge_nodes(plan, str(args.get("nodeA", "")), str(args.get("nodeB", "")), max_gap_mm)
    if name == "connect_corner":
        walls = {w.id: w for w in plan.walls}
        a, b = walls.get(args.get("wallA")), walls.get(args.get("wallB"))
        if a is None or b is None or a.id == b.id:
            return None, "invalid wall references"
        pairs = [(a.start_node, b.start_node), (a.start_node, b.end_node), (a.end_node, b.start_node), (a.end_node, b.end_node)]
        pairs = [pair for pair in pairs if pair[0] != pair[1]]
        if not pairs:
            return None, "walls already share a corner"
        keep, drop = min(
            pairs,
            key=lambda pair: math.hypot(
                plan.nodes[pair[0]].sketch_x - plan.nodes[pair[1]].sketch_x,
                plan.nodes[pair[0]].sketch_y - plan.nodes[pair[1]].sketch_y,
            ),
        )
        return _merge_nodes(plan, keep, drop, max_gap_mm)
    topology = build_topology(plan)
    dangling = topology.dangling_nodes
    if len(dangling) < 2:
        return None, "no open room endpoints found"
    pairs = [(a, b) for i, a in enumerate(dangling) for b in dangling[i + 1:]]
    keep, drop = min(
        pairs,
        key=lambda pair: math.hypot(
            plan.nodes[pair[0]].sketch_x - plan.nodes[pair[1]].sketch_x,
            plan.nodes[pair[0]].sketch_y - plan.nodes[pair[1]].sketch_y,
        ),
    )
    return _merge_nodes(plan, keep, drop, max_gap_mm)
