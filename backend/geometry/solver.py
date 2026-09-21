"""Solver metrico del rilievo (v2).

Obiettivo: la planimetria più fedele possibile a partire da uno schizzo grezzo, senza
impantanarsi in piccolezze.

- Le misure dichiarate non vengono mai modificate: sono i *target* del solver.
- Ogni misura ha un'incertezza realistica (GE360_MEASURE_SIGMA_MM, default 5 mm): il
  piccolo errore di chiusura di un rilievo vero viene distribuito su tutti i lati invece
  di storcere gli angoli.
- Gli angoli dello schizzo vengono "raddrizzati" parete per parete: quasi-orizzontali e
  quasi-verticali diventano ortogonali, i quasi-45° diventano smussi a 45°, il resto resta
  libero. Uno smusso non viene più forzato a 90°.
- Innesti a T e diagonali di controllo entrano come vincoli.
- Perdita robusta (soft_l1): un'ipotesi sbagliata (un angolo che non è retto, una misura
  sbagliata) non deforma tutto il resto.
- Se qualche lato resta fuori tolleranza, il solver prova a escludere una misura alla volta
  per trovare quella sbagliata e proporre il valore coerente con il resto del rilievo.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np
from scipy.optimize import least_squares

from backend.geometry.normalizer import NormalizedPlan, NormalizedWall
from backend.geometry.text_it import it
from backend.geometry.topology import TopologyResult

ANGLE_SIGMA_DEG = 0.8
DETERMINED_STD_MM = 30.0       # oltre questa incertezza un valore non è "ricavato dalle misure"          # stanze reali: fuori squadra tipico di qualche decimo di grado
SIGMA_PERP_RELAXED_MM = 40.0  # angoli nelle stanze triangolate da una diagonale
SIGMA_TEE_MM = 1.0


@dataclass
class SolverResult:
    node_positions: dict[str, tuple[float, float]]
    wall_meta: dict[str, dict[str, Any]]
    warnings: list[str]
    operations: list[dict[str, Any]]
    needs_review: bool
    closure_error_mm: float
    max_length_error_mm: float
    suspects: list[dict[str, Any]] = field(default_factory=list)
    diagonal_meta: list[dict[str, Any]] = field(default_factory=list)
    base_angle_deg: float = 0.0
    # registro delle decisioni autonome (niente domande all'utente)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    # configurazione della soluzione scelta, per rieseguirla nel Monte Carlo
    solve_config: dict[str, Any] = field(default_factory=dict)
    # innesti a T la cui posizione lungo la parete ospite non è fissata da nessuna misura
    undetermined_tees: list[dict[str, Any]] = field(default_factory=list)
    # pareti oblique la cui direzione dipende ancora dallo schizzo (serve una diagonale)
    sketch_shape_walls: list[str] = field(default_factory=list)


def _angle(vx, vy):
    return math.atan2(vy, vx)


def _wrap_pi(v):
    return (v + math.pi) % (2 * math.pi) - math.pi


def _angle_distance(a, b):
    return abs(_wrap_pi(a - b))


def acceptance_mm(length_mm: float, accept_abs_mm: float, accept_rel: float) -> float:
    return max(accept_abs_mm, accept_rel * length_mm)


def _sketch_angle(w: NormalizedWall) -> float:
    return _angle(w.sketch_b[0] - w.sketch_a[0], w.sketch_b[1] - w.sketch_a[1])


def _classify_angles(plan: NormalizedPlan, ortho_tol_deg: float, diag_tol_deg: float):
    """Angolo target per ogni parete + angolo base della pianta."""
    walls = plan.walls
    angles = {w.id: _sketch_angle(w) for w in walls}
    weights = {w.id: max(w.length_mm, 1.0) for w in walls}
    c = sum(weights[i] * math.cos(4 * a) for i, a in angles.items())
    s = sum(weights[i] * math.sin(4 * a) for i, a in angles.items())
    base = math.atan2(s, c) / 4.0 if abs(c) + abs(s) > 1e-12 else 0.0
    if abs(math.degrees(_wrap_pi(base))) <= 12:
        base = 0.0

    ortho_ok = []
    axes = set()
    for w in walls:
        cand = min((base + k * math.pi / 2 for k in range(-4, 5)), key=lambda t: _angle_distance(t, angles[w.id]))
        if _angle_distance(cand, angles[w.id]) <= math.radians(ortho_tol_deg):
            ortho_ok.append(w.id)
            axes.add(int(round((cand - base) / (math.pi / 2))) % 2)
    rectilinear = len(walls) >= 3 and len(axes) >= 2 and len(ortho_ok) / len(walls) >= 0.6

    targets: dict[str, float] = {}
    kinds: dict[str, str] = {}
    for w in walls:
        a = angles[w.id]
        if not rectilinear:
            targets[w.id], kinds[w.id] = a, "free"
            continue
        c90 = min((base + k * math.pi / 2 for k in range(-4, 5)), key=lambda t: _angle_distance(t, a))
        c45 = min((base + math.pi / 4 + k * math.pi / 2 for k in range(-4, 5)), key=lambda t: _angle_distance(t, a))
        r90, r45 = _angle_distance(c90, a), _angle_distance(c45, a)
        if r90 <= math.radians(ortho_tol_deg) and r90 <= r45:
            targets[w.id], kinds[w.id] = c90, "orthogonal"
        elif r45 <= math.radians(diag_tol_deg):
            targets[w.id], kinds[w.id] = c45, "diagonal45"
        else:
            targets[w.id], kinds[w.id] = a, "free"
    return base, targets, kinds, rectilinear


def _cycle_closure(graph: nx.MultiGraph, target_vectors: dict[str, tuple[float, float]]) -> float:
    simple = nx.Graph()
    for u, v, key, data in graph.edges(keys=True, data=True):
        if not simple.has_edge(u, v):
            simple.add_edge(u, v, wall_id=data["wall_id"])
    max_error = 0.0
    for cycle in nx.cycle_basis(simple):
        sx = sy = 0.0
        for i, u in enumerate(cycle):
            v = cycle[(i + 1) % len(cycle)]
            wid = simple.get_edge_data(u, v)["wall_id"]
            edge = next(d for _, _, _, d in graph.edges(keys=True, data=True) if d["wall_id"] == wid)
            sign = 1.0 if (u == edge.get("start_node") and v == edge.get("end_node")) else -1.0
            tv = target_vectors[wid]
            sx += tv[0] * sign
            sy += tv[1] * sign
        max_error = max(max_error, math.hypot(sx, sy))
    return max_error


def _components(plan: NormalizedPlan) -> list[set[str]]:
    g = nx.Graph()
    g.add_nodes_from(plan.nodes)
    wall_by_id = {w.id: w for w in plan.walls}
    for w in plan.walls:
        g.add_edge(w.start_node, w.end_node)
    for t in plan.tees:
        host = wall_by_id.get(t["wallId"])
        if host and t["node"] in plan.nodes:
            g.add_edge(t["node"], host.start_node)
    for d in plan.diagonals:
        g.add_edge(d["nodeA"], d["nodeB"])
    return [set(c) for c in nx.connected_components(g)]


def _initial_positions(plan: NormalizedPlan, targets: dict[str, float], node_ids: list[str]) -> np.ndarray:
    """Posizioni iniziali: si "cammina" sulle pareti con misure e angoli target.

    Così anche uno schizzo con proporzioni assurde parte da una forma già plausibile.
    """
    scale = plan.scale_mm_per_unit
    min_x = min(n.sketch_x for n in plan.nodes.values())
    min_y = min(n.sketch_y for n in plan.nodes.values())
    sketch = {nid: ((n.sketch_x - min_x) * scale, (n.sketch_y - min_y) * scale) for nid, n in plan.nodes.items()}
    adj: dict[str, list[tuple[str, NormalizedWall, float]]] = {n: [] for n in plan.nodes}
    for w in plan.walls:
        if w.start_node == w.end_node:
            continue
        adj[w.start_node].append((w.end_node, w, 1.0))
        adj[w.end_node].append((w.start_node, w, -1.0))
    pos: dict[str, tuple[float, float]] = {}
    for comp in _components(plan):
        root = min(comp, key=node_ids.index)
        pos[root] = sketch[root]
        queue = deque([root])
        while queue:
            u = queue.popleft()
            for v, w, sign in adj[u]:
                if v in pos:
                    continue
                th = targets[w.id]
                pos[v] = (pos[u][0] + sign * w.length_mm * math.cos(th), pos[u][1] + sign * w.length_mm * math.sin(th))
                queue.append(v)
        # nodi raggiunti solo tramite T/diagonali: posizionati relativamente allo schizzo
        for nid in comp:
            if nid not in pos:
                pos[nid] = (pos[root][0] + sketch[nid][0] - sketch[root][0], pos[root][1] + sketch[nid][1] - sketch[root][1])
    # innesti a T: posiziona il nodo sulla parete ospite
    wall_by_id = {w.id: w for w in plan.walls}
    for t in plan.tees:
        host = wall_by_id.get(t["wallId"])
        if host is None or t["node"] not in pos:
            continue
        a, b = pos[host.start_node], pos[host.end_node]
        tt = min(0.97, max(0.03, t["t"]))
        pos[t["node"]] = (a[0] + tt * (b[0] - a[0]), a[1] + tt * (b[1] - a[1]))
    return np.array([pos[n] for n in node_ids], dtype=float)


def perp_sigma_mm(length_mm: float, angle_sigma_deg: float) -> float:
    return max(2.0, length_mm * math.sin(math.radians(angle_sigma_deg)))


def _solve_once(plan, targets, kinds, *, sigma_mm, free_length_ids=frozenset(), relaxed=frozenset(),
                drop_len_ids=frozenset(), drop_dir_ids=frozenset(), length_overrides=None,
                angle_sigma_deg=ANGLE_SIGMA_DEG):
    """drop_len_ids / drop_dir_ids: pareti la cui lunghezza / direzione è già ricavabile dalle misure,
    quindi il valore dello schizzo non viene più usato nemmeno come suggerimento."""
    node_ids = list(plan.nodes)
    index = {n: i for i, n in enumerate(node_ids)}
    initial = _initial_positions(plan, targets, node_ids)
    anchors = []
    for comp in _components(plan):
        first = min(comp, key=lambda n: index[n])
        i = index[first]
        anchors.append((i, initial[i, 0], initial[i, 1]))
    wall_by_id = {w.id: w for w in plan.walls}
    tees = [t for t in plan.tees if t["wallId"] in wall_by_id and t["node"] in index]

    wall_rows = []
    overrides = length_overrides or {}
    for w in plan.walls:
        measured = w.measured and w.id not in free_length_ids
        length = overrides.get(w.id, w.length_mm)
        sig_len = sigma_mm if measured else max(50.0, 0.15 * length)
        kind = kinds[w.id]
        th = targets[w.id]
        if kind == "free":
            sig_dir = max(80.0, 0.25 * length)
        else:
            sig_dir = max(SIGMA_PERP_RELAXED_MM, perp_sigma_mm(length, angle_sigma_deg)) if w.id in relaxed \
                else perp_sigma_mm(length, angle_sigma_deg)
        wall_rows.append((index[w.start_node], index[w.end_node], length, sig_len, kind, math.cos(th), math.sin(th), sig_dir,
                          w.id in drop_len_ids and not measured, w.id in drop_dir_ids and kind == "free"))

    def residuals(flat):
        pts = flat.reshape((-1, 2))
        res = []
        for si, ei, length, sig_len, kind, ux, uy, sig_dir, no_len, no_dir in wall_rows:
            dx, dy = pts[ei, 0] - pts[si, 0], pts[ei, 1] - pts[si, 1]
            res.append(0.0 if no_len else (math.hypot(dx, dy) - length) / sig_len)
            if kind == "free":
                if no_dir:
                    res += [0.0, 0.0]
                else:
                    res += [(dx - length * ux) / sig_dir, (dy - length * uy) / sig_dir]
            else:
                res.append((ux * dy - uy * dx) / sig_dir)               # scostamento perpendicolare
                res.append(min(0.0, ux * dx + uy * dy) / sig_dir)       # niente pareti ribaltate
        for t in tees:
            host = wall_by_id[t["wallId"]]
            a, b, p = pts[index[host.start_node]], pts[index[host.end_node]], pts[index[t["node"]]]
            hx, hy = b[0] - a[0], b[1] - a[1]
            hl = math.hypot(hx, hy) or 1.0
            ux, uy = hx / hl, hy / hl
            px, py = p[0] - a[0], p[1] - a[1]
            res.append((ux * py - uy * px) / SIGMA_TEE_MM)
            res.append((ux * px + uy * py - t["t"] * hl) / max(100.0, 0.15 * hl))
        for d in plan.diagonals:
            a, b = pts[index[d["nodeA"]]], pts[index[d["nodeB"]]]
            res.append((math.hypot(b[0] - a[0], b[1] - a[1]) - d["lengthMm"]) / sigma_mm)
        for i, ax, ay in anchors:
            res += [(pts[i, 0] - ax) / 0.5, (pts[i, 1] - ay) / 0.5]
        return np.asarray(res)

    # minimi quadrati puri: gli errori grossi non si "assorbono", li spiega il motore delle ipotesi
    opt = least_squares(residuals, initial.reshape(-1), method="trf", loss="linear",
                        max_nfev=4000, xtol=1e-10, ftol=1e-10, gtol=1e-10)
    solved = opt.x.reshape((-1, 2))
    positions = {nid: (float(solved[index[nid], 0]), float(solved[index[nid], 1])) for nid in node_ids}
    # proietta esattamente i nodi a T sulla parete ospite (serve alla poligonizzazione)
    for t in tees:
        host = wall_by_id[t["wallId"]]
        a, b, p = positions[host.start_node], positions[host.end_node], positions[t["node"]]
        hx, hy = b[0] - a[0], b[1] - a[1]
        den = hx * hx + hy * hy or 1.0
        k = ((p[0] - a[0]) * hx + (p[1] - a[1]) * hy) / den
        positions[t["node"]] = (a[0] + k * hx, a[1] + k * hy)
    opt.ge360_layout = {"index": index, "n_wall_rows": 3 * len(plan.walls), "tees": tees, "residuals": residuals}
    return positions, opt


def _sketch_dependency(plan, positions, opt, kinds) -> dict:
    """Cosa è ricavabile SOLO dalle misure di cantiere e cosa dipende ancora dallo schizzo.

    Si tolgono dallo Jacobiano tutte le righe che vengono dal disegno (lunghezza delle pareti
    non misurate, direzione delle pareti libere, posizione degli innesti a T), si fissa la
    rotazione globale e si guarda lo spazio nullo: ogni grandezza che si può muovere lì dentro
    senza violare nessuna misura non è determinata dalle misure.
    """
    empty = {"unmeasured": {}, "freeWalls": {}, "tees": []}
    layout = getattr(opt, "ge360_layout", None)
    if not layout or opt.jac is None:
        return empty
    # Jacobiano a differenze centrali (errore ~1e-8): quello di least_squares è in avanti
    # (errore ~1e-4) e confonderebbe i modi davvero liberi con quelli debolmente vincolati.
    x0 = np.asarray(opt.x, dtype=float)
    fun = layout["residuals"]
    h = 1e-3
    cols = []
    for k in range(len(x0)):
        dx = np.zeros_like(x0)
        dx[k] = h
        cols.append((fun(x0 + dx) - fun(x0 - dx)) / (2 * h))
    jac = np.column_stack(cols) if cols else np.zeros((0, 0))
    index = layout["index"]
    n = jac.shape[1]
    drop = set()
    for k, w in enumerate(plan.walls):
        if not w.measured:
            drop.add(3 * k)
        if kinds[w.id] == "free":
            drop.update({3 * k + 1, 3 * k + 2})
    drop.update(layout["n_wall_rows"] + 2 * k + 1 for k in range(len(layout["tees"])))
    # per stabilire COSA è ricavabile dalle misure gli angoli contano "come da progetto"
    # (irrigiditi): l'incertezza del fuori squadra la misura poi il Monte Carlo
    angle_rows = {3 * k + 1 for k, w in enumerate(plan.walls) if kinds[w.id] != "free"}
    rows = [jac[r] * (25.0 if r in angle_rows else 1.0) for r in range(jac.shape[0]) if r not in drop]

    def angle_row(w):
        a, b = positions[w.start_node], positions[w.end_node]
        L = math.dist(a, b) or 1.0
        px, py = -(b[1] - a[1]) / L, (b[0] - a[0]) / L  # spostamento perpendicolare in mm
        row = np.zeros(n)
        i, j = index[w.start_node], index[w.end_node]
        row[2 * j], row[2 * j + 1] = px, py
        row[2 * i], row[2 * i + 1] = -px, -py
        return row

    def length_row(w):
        a, b = positions[w.start_node], positions[w.end_node]
        L = math.dist(a, b) or 1.0
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        row = np.zeros(n)
        i, j = index[w.start_node], index[w.end_node]
        row[2 * j], row[2 * j + 1] = ux, uy
        row[2 * i], row[2 * i + 1] = -ux, -uy
        return row

    # fissa la rotazione globale sulla parete misurata più lunga (non cambia nessuna misura)
    ref = max((w for w in plan.walls if w.measured and w.start_node != w.end_node), key=lambda w: w.length_mm, default=None)
    if ref is not None:
        rows.append(angle_row(ref) * float(np.max(np.abs(jac))))
    j = np.vstack(rows) if rows else np.zeros((0, n))
    # Covarianza a posteriori delle coordinate usando SOLO le misure (righe già divise per sigma):
    # una grandezza è "determinata" se la sua deviazione standard è piccola, non se è
    # matematicamente vincolata da effetti di secondo ordine.
    info = j.T @ j
    eps = 1e-9 * (np.trace(info) / max(1, n))
    cov = np.linalg.pinv(info + eps * np.eye(n))

    def free_along(row) -> bool:
        norm = float(np.linalg.norm(row)) or 1.0
        u = row / norm
        std_mm = math.sqrt(max(0.0, float(u @ cov @ u))) * norm
        return std_mm > DETERMINED_STD_MM

    out = {"unmeasured": {}, "freeWalls": {}, "tees": []}
    for w in plan.walls:
        if w.start_node == w.end_node:
            continue
        if not w.measured:
            out["unmeasured"][w.id] = not free_along(length_row(w))
        if kinds[w.id] == "free":
            out["freeWalls"][w.id] = not free_along(angle_row(w))
    wall_by_id = {w.id: w for w in plan.walls}
    for t in layout["tees"]:
        host = wall_by_id[t["wallId"]]
        a, b = positions[host.start_node], positions[host.end_node]
        hl = math.dist(a, b) or 1.0
        ux, uy = (b[0] - a[0]) / hl, (b[1] - a[1]) / hl
        row = np.zeros(n)
        i = index[t["node"]]
        row[2 * i], row[2 * i + 1] = ux, uy
        if free_along(row):
            out["tees"].append({"node": t["node"], "hostWallId": t["wallId"],
                                "partitionWallIds": sorted(w.id for w in plan.walls if t["node"] in (w.start_node, w.end_node)),
                                "offsetFromHostStartMm": round(math.dist(a, positions[t["node"]]), 1)})
    return out


def _errors(plan, positions, accept_abs_mm, accept_rel, free_length_ids=frozenset()):
    out = {}
    for w in plan.walls:
        a, b = positions[w.start_node], positions[w.end_node]
        calc = math.hypot(b[0] - a[0], b[1] - a[1])
        tol = acceptance_mm(w.length_mm, accept_abs_mm, accept_rel)
        measured = w.measured and w.id not in free_length_ids
        out[w.id] = (calc, abs(calc - w.length_mm), tol, measured)
    return out


def solve_geometry(
    plan: NormalizedPlan,
    topology: TopologyResult,
    *,
    orthogonal_tolerance_deg: float = 25.0,
    length_tolerance_mm: float = 0.5,  # mantenuto per compatibilità API
    angle_overrides: dict[str, float] | None = None,
    accept_abs_mm: float = 10.0,
    accept_rel: float = 0.005,
    sigma_mm: float = 5.0,
    diagonal_snap_deg: float = 12.0,
    analyse_outliers: bool = True,
    angle_sigma_deg: float = ANGLE_SIGMA_DEG,
    priors: dict[str, float] | None = None,
) -> SolverResult:
    base, targets, kinds, rectilinear = _classify_angles(plan, orthogonal_tolerance_deg, diagonal_snap_deg)
    wall_meta: dict[str, dict[str, Any]] = {}
    for w in plan.walls:
        wall_meta[w.id] = {
            "originalAngleDeg": math.degrees(_sketch_angle(w)),
            "targetAngleDeg": math.degrees(targets[w.id]),
            "orientation": kinds[w.id],
        }
    for wid, ang in (angle_overrides or {}).items():
        if wid in targets:
            targets[wid] = float(ang)
            kinds[wid] = "agent-constraint"
            wall_meta[wid]["orientation"] = "agent-constraint"
            wall_meta[wid]["targetAngleDeg"] = math.degrees(float(ang))

    operations: list[dict[str, Any]] = []
    if rectilinear:
        operations.append({
            "type": "orthogonal_component",
            "nodes": sorted(plan.nodes),
            "baseAngleDeg": round(math.degrees(base), 3),
            "orthogonalWalls": sorted(w for w, k in kinds.items() if k == "orthogonal"),
            "diagonalWalls": sorted(w for w, k in kinds.items() if k == "diagonal45"),
            "freeWalls": sorted(w for w, k in kinds.items() if k == "free"),
        })
    for gap in plan.closed_gaps:
        operations.append({"type": "auto_close_gap", **gap})
    for tee in plan.tees:
        operations.append({"type": "t_junction", **tee})

    diag_nodes = {d["nodeA"] for d in plan.diagonals} | {d["nodeB"] for d in plan.diagonals}
    relaxed = frozenset(w.id for w in plan.walls if {w.start_node, w.end_node} & diag_nodes)

    shape_decisions: list[dict[str, Any]] = []
    if rectilinear and analyse_outliers and not angle_overrides:
        from backend.geometry.hypotheses import classify_wall_shapes
        targets, kinds, shape_decisions = classify_wall_shapes(
            plan, targets, kinds, base, sigma_mm=sigma_mm, relaxed=relaxed, angle_sigma_deg=angle_sigma_deg)
        for wid, kind in kinds.items():
            wall_meta[wid]["orientation"] = kind
            wall_meta[wid]["targetAngleDeg"] = math.degrees(targets[wid])

    graph = topology.graph.copy()
    wall_by_id = {w.id: w for w in plan.walls}
    for _, _, _, data in graph.edges(keys=True, data=True):
        w = wall_by_id.get(data["wall_id"])
        if w:
            data["start_node"], data["end_node"] = w.start_node, w.end_node
    target_vectors = {w.id: (w.length_mm * math.cos(targets[w.id]), w.length_mm * math.sin(targets[w.id])) for w in plan.walls}
    try:
        closure = _cycle_closure(graph, target_vectors)
    except Exception:
        closure = 0.0

    positions, opt = _solve_once(plan, targets, kinds, sigma_mm=sigma_mm, relaxed=relaxed, angle_sigma_deg=angle_sigma_deg)
    dep = _sketch_dependency(plan, positions, opt, kinds)
    calc_len = frozenset(w for w, ok in dep["unmeasured"].items() if ok)
    calc_dir = frozenset(w for w, ok in dep["freeWalls"].items() if ok)
    drops = {"drop_len_ids": calc_len, "drop_dir_ids": calc_dir}
    if calc_len or calc_dir:
        # ricalcolo puro dalle misure: lo schizzo non influenza più ciò che è ricavabile
        positions, opt = _solve_once(plan, targets, kinds, sigma_mm=sigma_mm, relaxed=relaxed,
                                     angle_sigma_deg=angle_sigma_deg, **drops)
    errors = _errors(plan, positions, accept_abs_mm, accept_rel)
    out_of_tol = [wid for wid, (_, err, tol, measured) in errors.items() if measured and err > tol]
    diag_bad = []
    warnings = list(plan.warnings)
    suspects: list[dict[str, Any]] = []

    def diag_check(pos):
        rows, bad = [], []
        for d in plan.diagonals:
            a, b = pos[d["nodeA"]], pos[d["nodeB"]]
            calc = math.hypot(b[0] - a[0], b[1] - a[1])
            tol = acceptance_mm(d["lengthMm"], accept_abs_mm, accept_rel)
            rows.append({"id": d["id"], "lengthMm": d["lengthMm"], "calculatedLengthMm": calc,
                         "errorMm": abs(calc - d["lengthMm"]), "withinTolerance": abs(calc - d["lengthMm"]) <= tol})
            if abs(calc - d["lengthMm"]) > tol:
                bad.append(d["id"])
        return rows, bad

    diag_rows, diag_bad = diag_check(positions)

    # --- motore delle ipotesi: spiega le incoerenze e decide in autonomia -------------------
    from backend.geometry.hypotheses import resolve_inconsistencies

    decisions: list[dict[str, Any]] = []
    for i, d in enumerate(shape_decisions, start=1):
        decisions.append({"id": f"s{i}", **d})
    config = {"targets": dict(targets), "kinds": dict(kinds), "free_length_ids": frozenset(),
              "length_overrides": {}, "relaxed": relaxed, "ignored_diagonals": frozenset(),
              "alternatives": [], **drops}
    max_angle_dev = max((math.degrees(_angle_distance(
        _angle(positions[w.end_node][0] - positions[w.start_node][0], positions[w.end_node][1] - positions[w.start_node][1]),
        targets[w.id])) for w in plan.walls if kinds[w.id] != "free" and w.start_node != w.end_node), default=0.0)
    if analyse_outliers and (out_of_tol or diag_bad or max_angle_dev > 2.0 * angle_sigma_deg):
        outcome = resolve_inconsistencies(
            plan, targets, kinds, sigma_mm=sigma_mm, relaxed=relaxed, drops=drops,
            accept_abs_mm=accept_abs_mm, accept_rel=accept_rel, angle_sigma_deg=angle_sigma_deg,
            priors=priors,
        )
        positions, opt = outcome["positions"], outcome["opt"]
        config.update(outcome["config"])
        config["alternatives"] = [(prob, {**alt_cfg, "relaxed": relaxed}) for prob, alt_cfg in outcome["alternatives"]]
        targets, kinds = config["targets"], config["kinds"]
        for wid, kind in kinds.items():
            wall_meta[wid]["orientation"] = kind
        decisions += outcome["decisions"]
        for d in outcome["decisions"]:
            if d["kind"] in {"typo", "outlier"}:
                suspects.append({"wallId": d["wallId"], "declaredLengthMm": d["declaredMm"],
                                 "suggestedLengthMm": round(d["usedMm"], 1), "probability": d["probability"]})
                operations.append({"type": "suspect_measure", **{k: d[k] for k in ("wallId", "declaredMm", "usedMm", "probability")}})
        errors = _errors(plan, positions, accept_abs_mm, accept_rel)
        diag_rows, diag_bad = diag_check(positions)
        if closure > 2.0:
            warnings.append(f"Misure non chiuse ({closure:.1f} mm): risolto in autonomia, vedi decisioni")

    suspect_ids = {s["wallId"] for s in suspects}
    # Only a concrete, satisfied replacement explains a length residual.
    resolved = {}
    for d in decisions:
        wid = d.get("wallId")
        if d["kind"] not in {"typo", "outlier"} or wid not in errors:
            continue
        used = config["length_overrides"].get(wid, errors[wid][0])
        if abs(errors[wid][0] - used) <= acceptance_mm(used, accept_abs_mm, accept_rel):
            resolved[wid] = d["id"]
    sketch_shape_walls = sorted(w for w, ok in dep["freeWalls"].items() if not ok)
    max_err = 0.0
    needs_review = False
    for w in plan.walls:
        calc, err, tol, measured = errors[w.id]
        a, b = positions[w.start_node], positions[w.end_node]
        theta = _angle(b[0] - a[0], b[1] - a[1])
        within = (err <= tol) if measured else True
        if measured:
            max_err = max(max_err, err)
            # fuori tolleranza ma spiegato da una decisione: non serve revisione
            needs_review = needs_review or (not within and w.id not in resolved)
        angle_err = math.degrees(_angle_distance(theta, targets[w.id]))
        wall_meta[w.id].update(
            calculatedLengthMm=calc, lengthErrorMm=err, solvedAngleDeg=math.degrees(theta), angleErrorDeg=angle_err,
            measured=measured, toleranceMm=tol, withinTolerance=within, suspect=w.id in suspect_ids,
            suggestedLengthMm=next((s["suggestedLengthMm"] for s in suspects if s["wallId"] == w.id), None),
            lengthSource=("SUSPECT_MEASURED" if w.id in suspect_ids else "MEASURED")
            if w.measured else ("CALCULATED" if w.id in calc_len else "SKETCH"),
            shapeFromSketch=w.id in sketch_shape_walls,
            resolvedBy=resolved.get(w.id),
            usedLengthMm=config["length_overrides"].get(w.id, calc if w.id in config["free_length_ids"] else None),
        )
        if not w.measured:
            if w.id in calc_len:
                warnings.append(f"Parete {w.id} non misurata: calcolata {calc / 10:.1f} cm dalle altre misure")
            else:
                warnings.append(
                    f"Parete {w.id} non misurata e non ricavabile dalle misure: stimata {calc / 10:.0f} cm dallo schizzo"
                )
        if kinds[w.id] != "free" and angle_err > 2.0 and w.id not in resolved:
            warnings.append(f"Parete {w.id}: fuori squadra di {angle_err:.1f}°, come indicato dalle misure")
    tilted = []
    for w in plan.walls:
        if kinds[w.id] == "free" or w.id in resolved or w.start_node == w.end_node:
            continue
        dev = wall_meta[w.id].get("angleErrorDeg", 0.0)
        if dev > 1.0:
            tilted.append((dev, w.id))
    if tilted:
        worst = max(tilted)[0]
        decisions.append({
            "id": f"d{len(decisions) + 1}", "kind": "slightly_out_of_square", "probability": None,
            "wallIds": sorted(w for _, w in tilted), "deviationDeg": round(worst, 2),
            "text": it(f"Pareti {', '.join(sorted(w for _, w in tilted))} fuori squadra fino a {worst:.1f}°, come indicano le misure"),
        })
    undetermined = _sketch_dependency(plan, positions, opt, kinds)["tees"]
    for t in undetermined:
        warnings.append(
            f"Posizione del tramezzo {', '.join(t['partitionWallIds'])} sulla parete {t['hostWallId']} stimata dallo schizzo"
        )
    if any(d["id"] not in config["ignored_diagonals"] for d in diag_rows if not d["withinTolerance"]):
        needs_review = True
    if not opt.success:
        needs_review = True
        warnings.append(f"Geometry optimizer did not converge: {opt.message}")
    if needs_review and max_err > 0:
        warnings.append(f"Maximum authoritative length error is {max_err:.1f} mm")

    return SolverResult(
        node_positions=positions, wall_meta=wall_meta, warnings=warnings, operations=operations,
        needs_review=needs_review, closure_error_mm=closure, max_length_error_mm=max_err,
        suspects=suspects, diagonal_meta=diag_rows, base_angle_deg=math.degrees(base),
        undetermined_tees=undetermined,
        sketch_shape_walls=sketch_shape_walls,
        decisions=decisions,
        solve_config={**config, "sigma_mm": sigma_mm, "angle_sigma_deg": angle_sigma_deg},
    )
