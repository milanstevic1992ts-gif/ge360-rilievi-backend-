from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

import networkx as nx

from .models import FrontendPlanPayload


@dataclass
class TopologyNode:
    id: str
    source_points: list[tuple[float, float]] = field(default_factory=list)
    initial_mm: tuple[float, float] = (0.0, 0.0)
    max_snap_mm: float = 0.0


@dataclass
class TopologyEdge:
    wall_id: str
    a_node: str
    b_node: str
    source_a: tuple[float, float]
    source_b: tuple[float, float]
    length_mm: float
    stroke_id: str | None
    orientation_class: str = "FREE"
    sign: int = 1


@dataclass
class TopologyResult:
    graph: nx.Graph
    nodes: dict[str, TopologyNode]
    edges: list[TopologyEdge]
    mm_per_sketch_unit: float
    dominant_angle_rad: float
    merged_endpoint_count: int
    warnings: list[str]


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.r[a] < self.r[b]:
            a, b = b, a
        self.p[b] = a
        if self.r[a] == self.r[b]:
            self.r[a] += 1


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def estimate_scale_mm_per_unit(payload: FrontendPlanPayload) -> float:
    ratios: list[float] = []
    for wall in payload.walls:
        if wall.lengthCm is None:
            continue
        d = math.hypot(wall.b.x - wall.a.x, wall.b.y - wall.a.y)
        if d > 1e-9:
            ratios.append((wall.lengthCm * 10.0) / d)
    return median(ratios) if ratios else 10.0


def dominant_axis(payload: FrontendPlanPayload) -> float:
    sx = sy = 0.0
    count = 0
    total_weight = 0.0
    for wall in payload.walls:
        dx = wall.b.x - wall.a.x
        dy = wall.b.y - wall.a.y
        d = math.hypot(dx, dy)
        if d <= 1e-9:
            continue
        a = math.atan2(dy, dx)
        weight = wall.lengthCm or d
        sx += math.cos(2 * a) * weight
        sy += math.sin(2 * a) * weight
        total_weight += weight
        count += 1
    if count < 2 or total_weight <= 0 or abs(sx) + abs(sy) < 1e-12:
        return 0.0
    concentration = math.hypot(sx, sy) / total_weight
    if concentration < 0.55:
        return 0.0
    return 0.5 * math.atan2(sy, sx)


def _rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


def _angle_diff_axis(angle: float) -> tuple[float, str]:
    # Input is already in dominant-axis frame.
    a = (angle + math.pi) % math.pi
    candidates = [(0.0, "H"), (math.pi / 2, "V"), (math.pi, "H")]
    d, cls = min((abs(a - target), cls) for target, cls in candidates)
    return d, cls


def build_topology(
    payload: FrontendPlanPayload,
    *,
    snap_tolerance_mm: float = 250.0,
    axis_tolerance_deg: float = 18.0,
) -> TopologyResult:
    scale = estimate_scale_mm_per_unit(payload)
    theta = dominant_axis(payload)
    warnings: list[str] = []

    endpoints: list[dict] = []
    for wi, wall in enumerate(payload.walls):
        endpoints.append({"wall": wi, "end": "a", "p": (wall.a.x, wall.a.y)})
        endpoints.append({"wall": wi, "end": "b", "p": (wall.b.x, wall.b.y)})

    uf = _UnionFind(len(endpoints))
    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            if endpoints[i]["wall"] == endpoints[j]["wall"]:
                continue
            gap_mm = _dist(endpoints[i]["p"], endpoints[j]["p"]) * scale
            if gap_mm <= snap_tolerance_mm:
                uf.union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(endpoints)):
        groups[uf.find(i)].append(i)

    nodes: dict[str, TopologyNode] = {}
    endpoint_node: dict[tuple[int, str], str] = {}
    merged_count = 0
    for ni, members in enumerate(groups.values()):
        node_id = f"n{ni + 1}"
        xs = [endpoints[i]["p"][0] for i in members]
        ys = [endpoints[i]["p"][1] for i in members]
        avg = (sum(xs) / len(xs), sum(ys) / len(ys))
        max_gap = max((_dist(avg, endpoints[i]["p"]) * scale for i in members), default=0.0)
        rx, ry = _rotate(avg[0] * scale, avg[1] * scale, -theta)
        nodes[node_id] = TopologyNode(
            id=node_id,
            source_points=[endpoints[i]["p"] for i in members],
            initial_mm=(rx, ry),
            max_snap_mm=max_gap,
        )
        if len(members) > 1:
            merged_count += len(members) - 1
        for i in members:
            endpoint_node[(endpoints[i]["wall"], endpoints[i]["end"])] = node_id

    edges: list[TopologyEdge] = []
    tol = math.radians(axis_tolerance_deg)
    for wi, wall in enumerate(payload.walls):
        if wall.lengthCm is None:
            warnings.append(f"Muro {wall.id}: misura lengthCm mancante")
            continue
        dx = wall.b.x - wall.a.x
        dy = wall.b.y - wall.a.y
        rdx, rdy = _rotate(dx, dy, -theta)
        angle = math.atan2(rdy, rdx)
        d_axis, cls = _angle_diff_axis(angle)
        if d_axis > tol:
            cls = "FREE"
        if cls == "H":
            sign = 1 if rdx >= 0 else -1
        elif cls == "V":
            sign = 1 if rdy >= 0 else -1
        else:
            sign = 1
        edges.append(
            TopologyEdge(
                wall_id=wall.id,
                a_node=endpoint_node[(wi, "a")],
                b_node=endpoint_node[(wi, "b")],
                source_a=(wall.a.x, wall.a.y),
                source_b=(wall.b.x, wall.b.y),
                length_mm=wall.lengthCm * 10.0,
                stroke_id=wall.strokeId,
                orientation_class=cls,
                sign=sign,
            )
        )

    graph = nx.Graph()
    for node_id, node in nodes.items():
        graph.add_node(node_id, initial_mm=node.initial_mm, max_snap_mm=node.max_snap_mm)
    for edge in edges:
        graph.add_edge(edge.a_node, edge.b_node, wall_id=edge.wall_id, length_mm=edge.length_mm)

    return TopologyResult(
        graph=graph,
        nodes=nodes,
        edges=edges,
        mm_per_sketch_unit=scale,
        dominant_angle_rad=theta,
        merged_endpoint_count=merged_count,
        warnings=warnings,
    )
