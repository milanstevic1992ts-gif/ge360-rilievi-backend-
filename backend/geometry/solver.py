from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from scipy.optimize import least_squares

from backend.geometry.normalizer import NormalizedPlan, NormalizedWall
from backend.geometry.topology import TopologyResult


@dataclass
class SolverResult:
    node_positions: dict[str, tuple[float, float]]
    wall_meta: dict[str, dict[str, Any]]
    warnings: list[str]
    operations: list[dict[str, Any]]
    needs_review: bool
    closure_error_mm: float
    max_length_error_mm: float


def _angle(vx: float, vy: float) -> float:
    return math.atan2(vy, vx)


def _wrap_pi(value: float) -> float:
    return (value + math.pi) % (2 * math.pi) - math.pi


def _angle_distance(a: float, b: float) -> float:
    return abs(_wrap_pi(a - b))


def _component_orthogonal_base(walls: list[NormalizedWall], tolerance_deg: float) -> tuple[bool, float, dict[str, float]]:
    if len(walls) < 3:
        return False, 0.0, {}
    angles = [_angle(w.sketch_b[0] - w.sketch_a[0], w.sketch_b[1] - w.sketch_a[1]) for w in walls]
    c = sum(math.cos(4 * a) for a in angles)
    s = sum(math.sin(4 * a) for a in angles)
    base = math.atan2(s, c) / 4.0 if abs(c) + abs(s) > 1e-12 else angles[0]
    if abs(math.degrees(_wrap_pi(base))) <= 12:
        base = 0.0

    snapped: dict[str, float] = {}
    residuals: list[float] = []
    axes: set[int] = set()
    for wall, angle in zip(walls, angles):
        candidates = [base + k * math.pi / 2 for k in range(-4, 5)]
        chosen = min(candidates, key=lambda a: _angle_distance(a, angle))
        residual = _angle_distance(chosen, angle)
        residuals.append(residual)
        snapped[wall.id] = chosen
        axes.add(int(round((chosen - base) / (math.pi / 2))) % 2)
    ratio = sum(r <= math.radians(tolerance_deg) for r in residuals) / len(residuals)
    is_orthogonal = ratio >= 0.75 and len(axes) >= 2
    return is_orthogonal, base, snapped


def _cycle_closure(graph: nx.MultiGraph, target_vectors: dict[str, tuple[float, float]]) -> float:
    simple = nx.Graph()
    for u, v, key, data in graph.edges(keys=True, data=True):
        if not simple.has_edge(u, v):
            simple.add_edge(u, v, wall_id=data["wall_id"])
    max_error = 0.0
    for cycle in nx.cycle_basis(simple):
        if len(cycle) < 3:
            continue
        sx = sy = 0.0
        for i, u in enumerate(cycle):
            v = cycle[(i + 1) % len(cycle)]
            data = simple.get_edge_data(u, v)
            wall_id = data["wall_id"]
            tv = target_vectors[wall_id]
            edge_data = next(
                d for _, _, _, d in graph.edges(keys=True, data=True)
                if d["wall_id"] == wall_id
            )
            su = edge_data.get("start_node")
            sv = edge_data.get("end_node")
            sign = 1.0 if (u == su and v == sv) else -1.0
            sx += tv[0] * sign
            sy += tv[1] * sign
        max_error = max(max_error, math.hypot(sx, sy))
    return max_error


def solve_geometry(plan: NormalizedPlan, topology: TopologyResult, *,
                   orthogonal_tolerance_deg: float = 25.0,
                   length_tolerance_mm: float = 0.5,
                   angle_overrides: dict[str, float] | None = None) -> SolverResult:
    graph = topology.graph.copy()
    wall_by_id = {w.id: w for w in plan.walls}
    for u, v, key, data in graph.edges(keys=True, data=True):
        w = wall_by_id[data["wall_id"]]
        data["start_node"] = w.start_node
        data["end_node"] = w.end_node

    node_ids = list(plan.nodes)
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    scale = plan.scale_mm_per_unit
    min_x = min(n.sketch_x for n in plan.nodes.values())
    min_y = min(n.sketch_y for n in plan.nodes.values())
    initial = np.zeros((len(node_ids), 2), dtype=float)
    for node_id, node in plan.nodes.items():
        initial[index[node_id], 0] = (node.sketch_x - min_x) * scale
        initial[index[node_id], 1] = (node.sketch_y - min_y) * scale

    target_angles: dict[str, float] = {}
    wall_meta: dict[str, dict[str, Any]] = {}
    operations: list[dict[str, Any]] = []

    for component in topology.components:
        comp_walls = [w for w in plan.walls if w.start_node in component and w.end_node in component]
        orthogonal, base, snapped = _component_orthogonal_base(comp_walls, orthogonal_tolerance_deg)
        if orthogonal:
            operations.append({
                "type": "orthogonal_component",
                "nodes": sorted(component),
                "baseAngleDeg": round(math.degrees(base), 3),
            })
        for w in comp_walls:
            original = _angle(w.sketch_b[0] - w.sketch_a[0], w.sketch_b[1] - w.sketch_a[1])
            chosen = snapped[w.id] if orthogonal else original
            target_angles[w.id] = chosen
            wall_meta[w.id] = {
                "originalAngleDeg": math.degrees(original),
                "targetAngleDeg": math.degrees(chosen),
                "orientation": "orthogonal" if orthogonal else "free",
            }

    for wall_id, angle in (angle_overrides or {}).items():
        if wall_id in target_angles:
            target_angles[wall_id] = float(angle)
            wall_meta[wall_id]["orientation"] = "agent-constraint"
            wall_meta[wall_id]["targetAngleDeg"] = math.degrees(float(angle))

    target_vectors = {
        w.id: (w.length_mm * math.cos(target_angles[w.id]), w.length_mm * math.sin(target_angles[w.id]))
        for w in plan.walls
    }

    target_closure = _cycle_closure(graph, target_vectors)
    warnings = list(plan.warnings)
    needs_review = False
    if target_closure > max(2.0, length_tolerance_mm * 4):
        needs_review = True
        warnings.append(
            f"Authoritative lengths conflict with the inferred angle constraints; closure mismatch {target_closure:.1f} mm"
        )

    anchors: list[tuple[int, float, float]] = []
    for component in topology.components:
        first = min(component, key=lambda n: index[n])
        i = index[first]
        anchors.append((i, initial[i, 0], initial[i, 1]))

    x0 = initial.reshape(-1)

    def residuals(flat: np.ndarray) -> np.ndarray:
        pts = flat.reshape((-1, 2))
        res: list[float] = []
        for w in plan.walls:
            a = pts[index[w.start_node]]
            b = pts[index[w.end_node]]
            d = b - a
            length = float(np.hypot(d[0], d[1]))
            res.append((length - w.length_mm) / 0.05)
            theta = target_angles[w.id]
            tx, ty = w.length_mm * math.cos(theta), w.length_mm * math.sin(theta)
            direction_sigma = 6.0 if wall_meta[w.id]["orientation"] == "orthogonal" else 80.0
            res.append((d[0] - tx) / direction_sigma)
            res.append((d[1] - ty) / direction_sigma)
        for i, ax, ay in anchors:
            res.append((pts[i, 0] - ax) / 0.5)
            res.append((pts[i, 1] - ay) / 0.5)
        return np.asarray(res)

    opt = least_squares(residuals, x0, method="trf", max_nfev=5000, xtol=1e-12, ftol=1e-12, gtol=1e-12)
    solved = opt.x.reshape((-1, 2))

    node_positions = {node_id: (float(solved[index[node_id], 0]), float(solved[index[node_id], 1])) for node_id in node_ids}
    max_length_error = 0.0
    for w in plan.walls:
        a = node_positions[w.start_node]
        b = node_positions[w.end_node]
        calc = math.hypot(b[0] - a[0], b[1] - a[1])
        err = abs(calc - w.length_mm)
        max_length_error = max(max_length_error, err)
        theta = _angle(b[0] - a[0], b[1] - a[1])
        wall_meta[w.id]["calculatedLengthMm"] = calc
        wall_meta[w.id]["lengthErrorMm"] = err
        wall_meta[w.id]["solvedAngleDeg"] = math.degrees(theta)
        wall_meta[w.id]["angleErrorDeg"] = math.degrees(_angle_distance(theta, target_angles[w.id]))

    if max_length_error > length_tolerance_mm:
        needs_review = True
        warnings.append(f"Maximum authoritative length error is {max_length_error:.3f} mm")

    if not opt.success:
        needs_review = True
        warnings.append(f"Geometry optimizer did not converge: {opt.message}")

    return SolverResult(
        node_positions=node_positions,
        wall_meta=wall_meta,
        warnings=warnings,
        operations=operations,
        needs_review=needs_review,
        closure_error_mm=target_closure,
        max_length_error_mm=max_length_error,
    )
