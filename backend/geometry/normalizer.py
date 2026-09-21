"""Normalizzazione dello schizzo grezzo.

Lo schizzo del frontend è "a grandi linee": estremi che non si toccano, tramezzi che
si fermano prima della parete, lati non misurati, proporzioni sbagliate. Qui lo
trasformiamo in un grafo pulito di nodi e pareti, SENZA toccare le misure dichiarate:

1. scala mm/unità schizzo dalla mediana delle pareti misurate;
2. pareti non misurate -> lunghezza stimata dallo schizzo (vincolo debole nel solver);
3. aggancio degli estremi vicini (snap);
4. innesti a T: un estremo libero vicino al corpo di un'altra parete diventa un nodo
   vincolato a stare su quella parete;
5. chiusura automatica dei varchi rimasti (entro GE360_AUTO_CLOSE_MM);
6. diagonali di controllo agganciate ai nodi più vicini.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from backend.models import PlanPayload


@dataclass
class NormalizedNode:
    id: str
    sketch_x: float
    sketch_y: float
    source_endpoints: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class NormalizedWall:
    id: str
    start_node: str
    end_node: str
    sketch_a: tuple[float, float]
    sketch_b: tuple[float, float]
    length_mm: float
    source_length_cm: float | None
    thickness_mm: float
    height_mm: float
    raw: dict[str, Any]
    measured: bool = True


@dataclass
class NormalizedPlan:
    plan_id: str
    name: str
    nodes: dict[str, NormalizedNode]
    walls: list[NormalizedWall]
    openings: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    notes: list[Any]
    scale_mm_per_unit: float
    merged_gaps_mm: list[float]
    warnings: list[str]
    raw_payload: dict[str, Any]
    # nodo che termina a T sul corpo di un'altra parete: {"node","wallId","t"}
    tees: list[dict[str, Any]] = field(default_factory=list)
    # misure di controllo punto-punto: {"id","nodeA","nodeB","lengthMm"}
    diagonals: list[dict[str, Any]] = field(default_factory=list)
    # varchi chiusi automaticamente: {"nodeA","nodeB","gapMm"}
    closed_gaps: list[dict[str, Any]] = field(default_factory=list)
    wall_reference: str = "interior"


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_segment(p, a, b) -> tuple[float, float]:
    """Distanza punto-segmento e parametro t della proiezione (non clampato)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    if den <= 1e-12:
        return _distance(p, a), 0.0
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den
    tc = max(0.0, min(1.0, t))
    return _distance(p, (a[0] + tc * dx, a[1] + tc * dy)), t


def _degrees(walls: list[NormalizedWall]) -> dict[str, int]:
    deg: dict[str, int] = {}
    for w in walls:
        deg[w.start_node] = deg.get(w.start_node, 0) + 1
        deg[w.end_node] = deg.get(w.end_node, 0) + 1
    return deg


def _merge_node(nodes: dict[str, NormalizedNode], walls: list[NormalizedWall], keep: str, drop: str) -> bool:
    for w in walls:
        if {w.start_node, w.end_node} == {keep, drop}:
            return False  # collasserebbe una parete
    a, b = nodes[keep], nodes[drop]
    a.sketch_x, a.sketch_y = (a.sketch_x + b.sketch_x) / 2, (a.sketch_y + b.sketch_y) / 2
    a.source_endpoints.extend(b.source_endpoints)
    for w in walls:
        if w.start_node == drop:
            w.start_node = keep
        if w.end_node == drop:
            w.end_node = keep
    del nodes[drop]
    return True


def _find_tees(nodes, walls, tees, threshold_units) -> None:
    teed = {t["node"] for t in tees}
    deg = _degrees(walls)
    for nid, node in nodes.items():
        if deg.get(nid, 0) != 1 or nid in teed:
            continue
        p = (node.sketch_x, node.sketch_y)
        best = None
        for w in walls:
            if nid in (w.start_node, w.end_node):
                continue
            a = (nodes[w.start_node].sketch_x, nodes[w.start_node].sketch_y)
            b = (nodes[w.end_node].sketch_x, nodes[w.end_node].sketch_y)
            d, t = _point_segment(p, a, b)
            if d <= threshold_units and 0.03 < t < 0.97 and (best is None or d < best[0]):
                best = (d, w.id, t)
        if best is not None:
            tees.append({"node": nid, "wallId": best[1], "t": round(best[2], 6)})
            teed.add(nid)


def normalize_payload(
    payload: PlanPayload,
    *,
    default_thickness_mm: float = 120,
    default_height_mm: float = 2700,
    snap_tolerance_mm: float = 250,
    auto_close_mm: float = 600,
) -> NormalizedPlan:
    if not payload.walls:
        raise ValueError("plan has no walls")
    ratios = []
    for wall in payload.walls:
        if wall.lengthCm is None:
            continue
        d = math.hypot(wall.b.x - wall.a.x, wall.b.y - wall.a.y)
        if d > 1e-9:
            ratios.append(wall.lengthCm * 10.0 / d)
    if not ratios:
        raise ValueError("at least one measured wall is required")
    scale = median(ratios)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("invalid sketch scale")

    # --- 1. snap degli estremi vicini -------------------------------------------------
    endpoints = []
    for wi, wall in enumerate(payload.walls):
        endpoints += [
            {"wall_index": wi, "wall_id": wall.id, "end": "a", "p": (wall.a.x, wall.a.y)},
            {"wall_index": wi, "wall_id": wall.id, "end": "b", "p": (wall.b.x, wall.b.y)},
        ]
    uf = _UnionFind(len(endpoints))
    threshold_units = snap_tolerance_mm / scale
    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            if endpoints[i]["wall_index"] == endpoints[j]["wall_index"]:
                continue
            if _distance(endpoints[i]["p"], endpoints[j]["p"]) <= threshold_units:
                uf.union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(len(endpoints)):
        groups.setdefault(uf.find(i), []).append(i)
    node_for_endpoint = {}
    nodes: dict[str, NormalizedNode] = {}
    merged_gaps: list[float] = []
    for idx, members in enumerate(groups.values(), start=1):
        x = sum(endpoints[i]["p"][0] for i in members) / len(members)
        y = sum(endpoints[i]["p"][1] for i in members) / len(members)
        node_id = f"n{idx}"
        src = []
        if len(members) > 1:
            pts = [endpoints[i]["p"] for i in members]
            merged_gaps.append(max(_distance(a, b) for a in pts for b in pts) * scale)
        for i in members:
            key = (endpoints[i]["wall_id"], endpoints[i]["end"])
            node_for_endpoint[key] = node_id
            src.append(key)
        nodes[node_id] = NormalizedNode(node_id, x, y, src)

    # --- 2. pareti (misurate o stimate) -----------------------------------------------
    warnings: list[str] = []
    walls: list[NormalizedWall] = []
    plan_height = payload.wallHeightM * 1000 if payload.wallHeightM > 0 else default_height_mm
    for wall in payload.walls:
        s = node_for_endpoint[(wall.id, "a")]
        e = node_for_endpoint[(wall.id, "b")]
        if s == e:
            warnings.append(f"Wall {wall.id}: endpoints collapsed into the same topology node")
        sketch_len = math.hypot(wall.b.x - wall.a.x, wall.b.y - wall.a.y)
        measured = wall.lengthCm is not None
        length_mm = wall.lengthCm * 10.0 if measured else sketch_len * scale
        walls.append(NormalizedWall(
            id=wall.id, start_node=s, end_node=e,
            sketch_a=(wall.a.x, wall.a.y), sketch_b=(wall.b.x, wall.b.y),
            length_mm=length_mm, source_length_cm=wall.lengthCm,
            thickness_mm=wall.thicknessMm or default_thickness_mm,
            height_mm=wall.heightMm or plan_height, raw=wall.model_dump(mode="json"),
            measured=measured,
        ))

    # --- 3. innesti a T, chiusura varchi, di nuovo innesti ----------------------------
    tees: list[dict[str, Any]] = []
    closed_gaps: list[dict[str, Any]] = []
    _find_tees(nodes, walls, tees, threshold_units)

    close_limit_mm = max(auto_close_mm, snap_tolerance_mm)
    deg = _degrees(walls)
    teed = {t["node"] for t in tees}
    dangling = {n for n in nodes if deg.get(n, 0) == 1 and n not in teed}
    shortest: dict[str, float] = {}
    for w in walls:
        for n in (w.start_node, w.end_node):
            shortest[n] = min(shortest.get(n, math.inf), w.length_mm)
    candidates = []
    for a in dangling:
        for b in nodes:
            if a == b:
                continue
            gap_mm = _distance((nodes[a].sketch_x, nodes[a].sketch_y), (nodes[b].sketch_x, nodes[b].sketch_y)) * scale
            limit = min(close_limit_mm, 0.35 * min(shortest.get(a, math.inf), shortest.get(b, math.inf)))
            if gap_mm <= limit:
                candidates.append((b not in dangling, gap_mm, a, b))
    candidates.sort(key=lambda c: (c[0], c[1]))
    for _, gap_mm, a, b in candidates:
        if a not in nodes or b not in nodes:
            continue
        if _degrees(walls).get(a, 0) != 1:
            continue
        if _merge_node(nodes, walls, b, a):
            closed_gaps.append({"nodeA": a, "nodeB": b, "gapMm": round(gap_mm, 1)})
            merged_gaps.append(gap_mm)
            warnings.append(f"Varco di {gap_mm / 10:.0f} cm chiuso automaticamente")

    _find_tees(nodes, walls, tees, close_limit_mm / scale)
    tees = [t for t in tees if t["node"] in nodes]

    # --- 4. diagonali di controllo ----------------------------------------------------
    diagonals: list[dict[str, Any]] = []
    for diag in payload.diagonals:
        ends = []
        for p in ((diag.a.x, diag.a.y), (diag.b.x, diag.b.y)):
            nid, dist = min(
                ((n.id, _distance(p, (n.sketch_x, n.sketch_y))) for n in nodes.values()),
                key=lambda r: r[1],
            )
            ends.append(nid if dist * scale <= close_limit_mm else None)
        if None in ends or ends[0] == ends[1]:
            warnings.append(f"Diagonale {diag.id}: estremi non agganciabili a due angoli, ignorata")
            continue
        diagonals.append({"id": diag.id, "nodeA": ends[0], "nodeB": ends[1], "lengthMm": diag.lengthCm * 10.0})

    return NormalizedPlan(
        plan_id=payload.planId, name=payload.name, nodes=nodes, walls=walls,
        openings=[o.model_dump(mode="json") for o in payload.openings],
        rooms=[r.model_dump(mode="json") for r in payload.rooms], notes=list(payload.notes),
        scale_mm_per_unit=scale, merged_gaps_mm=merged_gaps, warnings=warnings,
        raw_payload=payload.model_dump(mode="json"),
        tees=tees, diagonals=diagonals, closed_gaps=closed_gaps,
        wall_reference=payload.wallReference,
    )
