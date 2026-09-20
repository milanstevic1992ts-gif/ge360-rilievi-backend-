from __future__ import annotations

import copy
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from .models import (
    Ceiling,
    Floor,
    FrontendPlanPayload,
    Node,
    Opening,
    Point2D,
    ProcessedPlan,
    QualityReport,
    Room,
    Wall,
)
from .topology import TopologyEdge, TopologyResult, build_topology


@dataclass
class SolverConfig:
    snap_tolerance_mm: float = 250.0
    axis_tolerance_deg: float = 18.0
    length_tolerance_mm: float = 0.05
    closure_tolerance_mm: float = 2.0
    default_wall_thickness_mm: float = 120.0


@dataclass
class SolveResult:
    plan: ProcessedPlan
    operations: list[dict]
    topology: TopologyResult


def _edge_delta(edge: TopologyEdge, topology: TopologyResult) -> tuple[float, float]:
    if edge.orientation_class == "H":
        return edge.sign * edge.length_mm, 0.0
    if edge.orientation_class == "V":
        return 0.0, edge.sign * edge.length_mm
    # Truly diagonal/free: retain only the sketch direction, never its scale.
    ax, ay = edge.source_a
    bx, by = edge.source_b
    c, s = math.cos(-topology.dominant_angle_rad), math.sin(-topology.dominant_angle_rad)
    dx, dy = bx - ax, by - ay
    rx, ry = dx * c - dy * s, dx * s + dy * c
    d = math.hypot(rx, ry)
    if d <= 1e-9:
        return edge.length_mm, 0.0
    return rx / d * edge.length_mm, ry / d * edge.length_mm


def _solve_graph(topology: TopologyResult, cfg: SolverConfig) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[tuple[float, float], tuple[float, float], bool]], float, list[str]]:
    adjacency: dict[str, list[tuple[TopologyEdge, bool]]] = defaultdict(list)
    for e in topology.edges:
        adjacency[e.a_node].append((e, True))
        adjacency[e.b_node].append((e, False))

    node_pos: dict[str, tuple[float, float]] = {}
    edge_pos: dict[str, tuple[tuple[float, float], tuple[float, float], bool]] = {}
    warnings: list[str] = []
    max_closure = 0.0

    for component in __import__("networkx").connected_components(topology.graph):
        root = min(component)
        root_initial = topology.nodes[root].initial_mm
        node_pos[root] = root_initial
        q = deque([root])
        while q:
            n = q.popleft()
            base = node_pos[n]
            for edge, forward in adjacency[n]:
                dx, dy = _edge_delta(edge, topology)
                if not forward:
                    dx, dy = -dx, -dy
                other = edge.b_node if forward else edge.a_node
                candidate = (base[0] + dx, base[1] + dy)
                if other not in node_pos:
                    node_pos[other] = candidate
                    q.append(other)
                else:
                    gap = math.hypot(candidate[0] - node_pos[other][0], candidate[1] - node_pos[other][1])
                    max_closure = max(max_closure, gap)
                    if gap > cfg.closure_tolerance_mm:
                        warnings.append(
                            f"Muro {edge.wall_id}: vincoli incompatibili, errore di chiusura {gap/10:.2f} cm"
                        )

    # Derive each wall independently from its authoritative length. If a cycle is incompatible,
    # the offending wall remains exact and a visible gap is left instead of changing the measure.
    for edge in topology.edges:
        start = node_pos.get(edge.a_node, topology.nodes[edge.a_node].initial_mm)
        dx, dy = _edge_delta(edge, topology)
        exact_end = (start[0] + dx, start[1] + dy)
        shared_end = node_pos.get(edge.b_node, exact_end)
        gap = math.hypot(exact_end[0] - shared_end[0], exact_end[1] - shared_end[1])
        compatible = gap <= cfg.closure_tolerance_mm
        if compatible:
            exact_end = shared_end
        edge_pos[edge.wall_id] = (start, exact_end, compatible)

    return node_pos, edge_pos, max_closure, warnings


def _build_openings(payload: FrontendPlanPayload, walls: list[Wall]) -> tuple[list[Opening], list[str]]:
    wall_map = {w.id: w for w in walls}
    out: list[Opening] = []
    warnings: list[str] = []
    for src in payload.openings:
        wall = wall_map.get(src.wallId)
        if not wall:
            warnings.append(f"Apertura {src.id}: muro {src.wallId} non trovato")
            continue
        width = src.widthCm * 10.0
        height = (src.heightCm * 10.0) if src.heightCm is not None else (2100.0 if src.type == "door" else 1200.0)
        sill = (src.sillHeightCm * 10.0) if src.sillHeightCm is not None else (0.0 if src.type == "door" else 900.0)
        if src.offsetCm is not None:
            offset = src.offsetCm * 10.0
        elif src.position is not None:
            center = max(0.0, min(1.0, src.position)) * wall.lengthMm
            offset = center - width / 2 if src.referenceEnd == "a" else wall.lengthMm - center - width / 2
        else:
            offset = max(0.0, (wall.lengthMm - width) / 2)
        center_from_start = offset + width / 2 if src.referenceEnd == "a" else wall.lengthMm - offset - width / 2
        valid = offset >= -1e-6 and offset + width <= wall.lengthMm + 1e-6 and height > 0 and width > 0
        warning = None
        if not valid:
            warning = f"Apertura {src.id}: offset/larghezza incompatibili con il muro {wall.id}"
            warnings.append(warning)
        out.append(
            Opening(
                id=src.id,
                type=src.type,
                wallId=src.wallId,
                widthMm=width,
                heightMm=height,
                sillHeightMm=sill,
                offsetMm=offset,
                referenceEnd=src.referenceEnd,
                centerFromStartMm=center_from_start,
                valid=valid,
                warning=warning,
            )
        )
    return out, warnings


def _match_wall_ids(poly: Polygon, walls: list[Wall], tol_mm: float = 5.0) -> list[str]:
    boundary = poly.boundary
    ids: list[str] = []
    for wall in walls:
        line = LineString([(wall.start.x, wall.start.y), (wall.end.x, wall.end.y)])
        if boundary.buffer(tol_mm).contains(line.interpolate(0.5, normalized=True)):
            ids.append(wall.id)
    return ids


def detect_rooms(
    walls: list[Wall],
    source_rooms: Iterable,
    *,
    height_mm: float,
    estimated: bool,
    needs_review: bool,
) -> list[Room]:
    usable = [w for w in walls if w.solved]
    lines = [LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)]) for w in usable]
    if not lines:
        return []
    polygons = [p for p in polygonize(unary_union(lines)) if p.area > 10_000]
    polygons.sort(key=lambda p: (p.centroid.y, p.centroid.x))
    source_rooms = list(source_rooms)
    out: list[Room] = []
    for i, poly in enumerate(polygons, start=1):
        wall_ids = _match_wall_ids(poly, usable)
        name = f"Ambiente {i}"
        best_score = 0.0
        for src in source_rooms:
            wanted = set(src.wallIds)
            if not wanted:
                continue
            got = set(wall_ids)
            score = len(wanted & got) / max(1, len(wanted | got))
            if score > best_score:
                best_score = score
                if src.name:
                    name = src.name
        area = poly.area / 1_000_000.0
        perimeter = poly.length / 1000.0
        quality = "NEEDS_REVIEW" if needs_review else ("ESTIMATED" if estimated else "OK")
        out.append(
            Room(
                roomId=f"room-{i}",
                name=name,
                polygon=[Point2D(x=x, y=y) for x, y in list(poly.exterior.coords)[:-1]],
                wallIds=wall_ids,
                floorAreaM2=area,
                ceilingAreaM2=area,
                perimeterM=perimeter,
                grossWallAreaM2=perimeter * (height_mm / 1000.0),
                quality=quality,
            )
        )
    return out


def validate_lengths(walls: list[Wall]) -> tuple[float, list[str]]:
    max_err = 0.0
    warnings: list[str] = []
    for wall in walls:
        calc = math.hypot(wall.end.x - wall.start.x, wall.end.y - wall.start.y)
        err = abs(calc - wall.lengthMm)
        max_err = max(max_err, err)
        if err > 0.05:
            warnings.append(f"Muro {wall.id}: errore lunghezza {err:.4f} mm")
    return max_err, warnings


def geometry_score(plan: ProcessedPlan) -> float:
    score = 100.0
    score -= min(50.0, plan.quality.closureErrorCm * 5.0)
    score -= min(30.0, plan.quality.maxLengthErrorMm * 100.0)
    score -= 3.0 * len(plan.quality.warnings)
    score += min(10.0, 2.0 * len(plan.rooms))
    return max(0.0, min(100.0, score))


def solve_plan(payload: FrontendPlanPayload, version: int, cfg: SolverConfig) -> SolveResult:
    topology = build_topology(
        payload,
        snap_tolerance_mm=cfg.snap_tolerance_mm,
        axis_tolerance_deg=cfg.axis_tolerance_deg,
    )
    node_pos, edge_pos, closure_mm, solve_warnings = _solve_graph(topology, cfg)
    src_by_id = {w.id: w for w in payload.walls}
    walls: list[Wall] = []
    operations: list[dict] = []

    for edge in topology.edges:
        src = src_by_id[edge.wall_id]
        start, end, compatible = edge_pos[edge.wall_id]
        thickness = src.thicknessMm or cfg.default_wall_thickness_mm
        height = src.heightMm or payload.wallHeightM * 1000.0
        walls.append(
            Wall(
                id=edge.wall_id,
                startNodeId=edge.a_node,
                endNodeId=edge.b_node,
                start=Point2D(x=start[0], y=start[1]),
                end=Point2D(x=end[0], y=end[1]),
                lengthMm=edge.length_mm,
                heightMm=height,
                thicknessMm=thickness,
                sourceLengthCm=float(src.lengthCm),
                sourceA=src.a,
                sourceB=src.b,
                strokeId=src.strokeId,
                orientationClass=edge.orientation_class,
                solved=compatible,
            )
        )
        operations.append({
            "type": "normalize_wall",
            "wallId": edge.wall_id,
            "declaredLengthMm": edge.length_mm,
            "orientation": edge.orientation_class,
            "connected": compatible,
        })

    nodes = [
        Node(
            id=node_id,
            x=node_pos.get(node_id, n.initial_mm)[0],
            y=node_pos.get(node_id, n.initial_mm)[1],
            sourcePoints=[Point2D(x=x, y=y) for x, y in n.source_points],
            snapDistanceMm=n.max_snap_mm,
        )
        for node_id, n in topology.nodes.items()
    ]
    openings, opening_warnings = _build_openings(payload, walls)
    max_len_err, length_warnings = validate_lengths(walls)
    incompatible_wall = any(not w.solved for w in walls)
    invalid_opening = any(not o.valid for o in openings)
    missing_measure = len(walls) != len(payload.walls)
    needs_review = (
        closure_mm > cfg.closure_tolerance_mm
        or max_len_err > cfg.length_tolerance_mm
        or incompatible_wall
        or invalid_opening
        or missing_measure
    )
    estimated = topology.merged_endpoint_count > 0
    height_mm = payload.wallHeightM * 1000.0
    rooms = detect_rooms(
        walls,
        payload.rooms,
        height_mm=height_mm,
        estimated=estimated,
        needs_review=needs_review,
    )
    warnings = topology.warnings + solve_warnings + opening_warnings + length_warnings
    if not rooms and len(walls) >= 3 and not needs_review:
        warnings.append("Nessun ambiente chiuso riconosciuto")
    quality_status = "NEEDS_REVIEW" if needs_review else ("ESTIMATED" if estimated else "OK")
    quality = QualityReport(
        status=quality_status,
        closureErrorCm=closure_mm / 10.0,
        maxLengthErrorMm=max_len_err,
        geometryScore=0.0,
        warnings=warnings,
    )
    plan = ProcessedPlan(
        planId=payload.planId,
        name=payload.name,
        version=version,
        nodes=nodes,
        walls=walls,
        openings=openings,
        rooms=rooms,
        floor=Floor(roomIds=[r.roomId for r in rooms]),
        ceiling=Ceiling(roomIds=[r.roomId for r in rooms]),
        quality=quality,
        needsReview=needs_review,
        source={
            "frontendVersion": payload.version,
            "kind": payload.kind,
            "wallHeightM": payload.wallHeightM,
            "rawWallCount": len(payload.walls),
            "sourceLengthsCm": {w.id: w.lengthCm for w in payload.walls},
        },
    )
    plan.quality.geometryScore = geometry_score(plan)
    return SolveResult(plan=plan, operations=operations, topology=topology)


# Deterministic geometry tool surface used by the optional agent.
def snap_endpoints(plan: ProcessedPlan) -> ProcessedPlan:
    return copy.deepcopy(plan)


def merge_nodes(plan: ProcessedPlan) -> ProcessedPlan:
    return copy.deepcopy(plan)


def connect_corner(plan: ProcessedPlan, wall_a: str, wall_b: str) -> ProcessedPlan:
    return copy.deepcopy(plan)


def make_parallel(plan: ProcessedPlan, wall_a: str, wall_b: str) -> ProcessedPlan:
    return copy.deepcopy(plan)


def make_perpendicular(plan: ProcessedPlan, wall_a: str, wall_b: str) -> ProcessedPlan:
    return copy.deepcopy(plan)


def close_small_gap(plan: ProcessedPlan) -> ProcessedPlan:
    return copy.deepcopy(plan)


def align_collinear(plan: ProcessedPlan) -> ProcessedPlan:
    return copy.deepcopy(plan)


def find_intersections(plan: ProcessedPlan) -> list[dict]:
    intersections: list[dict] = []
    for i, a in enumerate(plan.walls):
        la = LineString([(a.start.x, a.start.y), (a.end.x, a.end.y)])
        for b in plan.walls[i + 1:]:
            lb = LineString([(b.start.x, b.start.y), (b.end.x, b.end.y)])
            hit = la.intersection(lb)
            if isinstance(hit, Point) and not hit.is_empty:
                intersections.append({"wallA": a.id, "wallB": b.id, "x": hit.x, "y": hit.y})
    return intersections
