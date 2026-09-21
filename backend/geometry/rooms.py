"""Rilevamento stanze e computo per singolo ambiente.

Per ogni stanza restituisce pavimento, soffitto, pareti faccia per faccia (lorde,
aperture, nette, spallette, rivestimento), battiscopa, volume, adiacenze e qualità.
"""
from __future__ import annotations

import math
import re
from statistics import median

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult
from backend.models import OpeningModel, PointMM, QualityStatus, RoomModel, RoomOpening, RoomWallFace

ROOM_TYPES = [
    ("bagno", ("bagno", "wc", "servizio", "toilette", "doccia", "lavanderia")),
    ("cucina", ("cucina", "cottura", "kitchen")),
    ("camera", ("camera", "letto", "cameretta", "matrimoniale")),
    ("soggiorno", ("soggiorno", "salotto", "sala", "living", "salone", "pranzo")),
    ("disimpegno", ("corridoio", "disimpegno", "ingresso", "andito", "atrio", "passaggio")),
    ("ripostiglio", ("ripostiglio", "sgabuzzino", "cabina", "armadio", "deposito")),
    ("studio", ("studio", "ufficio")),
    ("esterno", ("balcone", "terrazzo", "terrazza", "loggia", "veranda")),
]
ALLOWED_TYPES = {t for t, _ in ROOM_TYPES} | {"altro"}
FACE_MARGIN_MM = 15.0


def classify_room_type(name: str | None, explicit: str | None = None) -> str:
    if explicit and explicit.lower() in ALLOWED_TYPES:
        return explicit.lower()
    text = (name or "").lower()
    for room_type, words in ROOM_TYPES:
        if any(re.search(rf"\b{re.escape(w)}", text) for w in words):
            return room_type
    return "altro"


def _best_room_match(wall_ids, provided):
    got = set(wall_ids)
    best, best_score = None, 0.0
    for room in provided:
        wanted = set(room.get("wallIds") or [])
        if not wanted:
            continue
        union = got | wanted
        score = len(got & wanted) / len(union) if union else 0
        if score > best_score:
            best_score, best = score, room
    return best if best is not None and best_score >= 0.4 else None


def _wall_lines(plan: NormalizedPlan, solved: SolverResult) -> dict[str, LineString]:
    tee_nodes = {t["node"] for t in plan.tees}
    lines = {}
    for w in plan.walls:
        a = solved.node_positions[w.start_node]
        b = solved.node_positions[w.end_node]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        # prolunga di 2 mm le estremità a T così la parete ospite viene "tagliata"
        if w.start_node in tee_nodes:
            a = (a[0] - ux * 2.0, a[1] - uy * 2.0)
        if w.end_node in tee_nodes:
            b = (b[0] + ux * 2.0, b[1] + uy * 2.0)
        lines[w.id] = LineString([a, b])
    return lines


def _largest(geom) -> Polygon | None:
    if geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    return max(polys, key=lambda g: g.area) if polys else None


def _faces(poly: Polygon, wall_lines: dict[str, LineString], thickness: dict[str, float]):
    """Spigoli del poligono netto -> facce di parete (con wallId)."""
    coords = list(orient(poly, 1.0).exterior.coords)
    raw = []
    for p, q in zip(coords[:-1], coords[1:]):
        seg = LineString([p, q])
        if seg.length < 1.0:
            continue
        mid = seg.interpolate(0.5, normalized=True)
        sx, sy = (q[0] - p[0]) / seg.length, (q[1] - p[1]) / seg.length
        best = None
        for wid, line in wall_lines.items():
            (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
            ll = math.hypot(x1 - x0, y1 - y0) or 1.0
            if abs(sx * (y1 - y0) / ll - sy * (x1 - x0) / ll) > 0.05:
                continue  # non parallelo
            d = line.distance(mid)
            if d <= thickness[wid] / 2 + FACE_MARGIN_MM and (best is None or d < best[0]):
                best = (d, wid)
        raw.append({"wallId": best[1] if best else None, "p": p, "q": q, "length": seg.length})
    merged = []
    for face in raw:
        if merged and merged[-1]["wallId"] == face["wallId"] and face["wallId"] is not None:
            merged[-1]["q"] = face["q"]
            merged[-1]["length"] += face["length"]
        else:
            merged.append(dict(face))
    if len(merged) > 1 and merged[0]["wallId"] is not None and merged[0]["wallId"] == merged[-1]["wallId"]:
        merged[0]["p"] = merged[-1]["p"]
        merged[0]["length"] += merged[-1]["length"]
        merged.pop()
    return merged


def _partition_walls(lines: dict[str, LineString], polygons: list[Polygon]) -> set[str]:
    """Tramezzi = pareti con una stanza su entrambi i lati."""
    if len(polygons) < 2:
        return set()
    inside = unary_union(polygons)
    out = set()
    for wid, line in lines.items():
        (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
        ll = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / ll, (x1 - x0) / ll
        for frac in (0.25, 0.5, 0.75):
            m = line.interpolate(frac, normalized=True)
            left = Point(m.x + nx * 50, m.y + ny * 50)
            right = Point(m.x - nx * 50, m.y - ny * 50)
            if inside.contains(left) and inside.contains(right):
                out.add(wid)
                break
    return out


def _overlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def detect_rooms(plan: NormalizedPlan, solved: SolverResult, openings: list[OpeningModel] | None = None, *,
                 bath_tiling_height_mm: float = 2200.0,
                 room_hints: dict[str, dict] | None = None) -> list[RoomModel]:
    """room_hints: {roomId: {"name":..., "type":...}} proposti dall'IA per le stanze senza nome."""
    openings = openings or []
    room_hints = room_hints or {}
    wall_by_id = {w.id: w for w in plan.walls}
    thickness = {w.id: w.thickness_mm for w in plan.walls}
    lines = _wall_lines(plan, solved)
    polygons = [p for p in polygonize(unary_union(list(lines.values()))) if p.area > 10_000]
    polygons.sort(key=lambda p: (round(p.centroid.y, 3), round(p.centroid.x, 3)))

    boundary_ids = []
    for poly in polygons:
        ids = sorted(wid for wid, line in lines.items() if poly.boundary.intersection(line).length > 1.0)
        boundary_ids.append(ids)
    shared_walls = _partition_walls(lines, polygons)
    if plan.wall_reference == "axis":
        deduct = set(wall_by_id)
    elif plan.wall_reference == "partitionAxis":
        deduct = shared_walls
    else:
        deduct = set()

    # abbinamento 1:1 stanze calcolate <-> stanze del frontend (migliore sovrapposizione prima)
    pairs = []
    for i, ids in enumerate(boundary_ids):
        for j, fr in enumerate(plan.rooms):
            wanted = set(fr.get("wallIds") or [])
            if wanted:
                union = set(ids) | wanted
                score = len(set(ids) & wanted) / len(union)
                if score >= 0.4:
                    pairs.append((score, i, j))
    matches: dict[int, dict] = {}
    used: set[int] = set()
    for score, i, j in sorted(pairs, reverse=True):
        if i not in matches and j not in used:
            matches[i] = plan.rooms[j]
            used.add(j)
    undetermined_by_wall: dict[str, list[dict]] = {}
    for t in solved.undetermined_tees:
        for w in t["partitionWallIds"]:
            undetermined_by_wall.setdefault(w, []).append(t)
    suspects = {s["wallId"]: s for s in solved.suspects}
    rooms: list[RoomModel] = []
    for idx, (gross, wall_ids) in enumerate(zip(polygons, boundary_ids), start=1):
        match = matches.get(idx - 1)
        net = gross
        cut = [lines[w].buffer(thickness[w] / 2, cap_style=2, join_style=2) for w in wall_ids if w in deduct]
        if cut:
            net = _largest(gross.difference(unary_union(cut))) or gross
        name = (match or {}).get("name") or f"Ambiente {idx}"
        room_id = (match or {}).get("id") or f"room-{idx}"
        room_type = classify_room_type(name, (match or {}).get("type"))
        hint = room_hints.get(room_id) or {}
        if not match or not match.get("name"):
            name = hint.get("name") or name
        if room_type == "altro":
            room_type = classify_room_type(name, hint.get("type"))

        if match and match.get("heightCm"):
            height_mm, height_src = float(match["heightCm"]) * 10, "USER"
        else:
            hs = [wall_by_id[w].height_mm for w in wall_ids if w in wall_by_id]
            height_mm, height_src = (float(median(hs)) if hs else 2700.0), "WALLS"
        tiling_h = None
        if match and match.get("tilingHeightCm"):
            tiling_h = float(match["tilingHeightCm"]) * 10
        elif room_type == "bagno":
            tiling_h = bath_tiling_height_mm
        if tiling_h is not None:
            tiling_h = min(tiling_h, height_mm)

        faces_raw = _faces(net, {w: lines[w] for w in wall_ids}, thickness)
        faces: list[RoomWallFace] = []
        room_openings: list[RoomOpening] = []
        door_width_total = 0.0
        for f in faces_raw:
            wid = f["wallId"]
            seg = LineString([f["p"], f["q"]])
            length = f["length"]
            face = RoomWallFace(
                wallId=wid, lengthMm=round(length, 1), heightMm=height_mm,
                grossAreaM2=length * height_mm / 1e6,
                orientationDeg=round(math.degrees(math.atan2(f["q"][1] - f["p"][1], f["q"][0] - f["p"][0])), 2),
                shared=wid in shared_walls,
            )
            tiling = length * tiling_h if tiling_h is not None else None
            for op in openings:
                if op.wallId != wid:
                    continue
                c = Point(op.center.x, op.center.y)
                if seg.distance(c) > thickness[wid] / 2 + FACE_MARGIN_MM:
                    continue
                s = seg.project(c)
                if s < -op.widthMm / 2 or s > length + op.widthMm / 2:
                    continue
                h = min(op.heightMm, max(0.0, height_mm - op.sillHeightMm))
                area = op.widthMm * h / 1e6
                depth = thickness[wid] / 2 if wid in shared_walls else thickness[wid]
                reveal = (2 * h + op.widthMm) * depth / 1e6
                face.openingIds.append(op.id)
                face.openingsAreaM2 += area
                face.revealAreaM2 += reveal
                if tiling is not None:
                    tiling -= op.widthMm * _overlap(op.sillHeightMm, op.sillHeightMm + h, 0.0, tiling_h)
                if op.type == "door":
                    door_width_total += op.widthMm
                room_openings.append(RoomOpening(
                    id=op.id, type=op.type, wallId=wid, widthMm=op.widthMm, heightMm=op.heightMm,
                    sillHeightMm=op.sillHeightMm, areaM2=round(area, 4), revealAreaM2=round(reveal, 4),
                ))
            face.netAreaM2 = max(0.0, face.grossAreaM2 - face.openingsAreaM2)
            if tiling is not None:
                face.tilingAreaM2 = round(max(0.0, tiling) / 1e6, 4)
            face.grossAreaM2 = round(face.grossAreaM2, 4)
            face.openingsAreaM2 = round(face.openingsAreaM2, 4)
            face.netAreaM2 = round(face.netAreaM2, 4)
            face.revealAreaM2 = round(face.revealAreaM2, 4)
            faces.append(face)

        floor = net.area / 1e6
        perimeter = net.length / 1000
        gross_walls = sum(f.grossAreaM2 for f in faces)
        openings_area = sum(f.openingsAreaM2 for f in faces)
        net_walls = sum(f.netAreaM2 for f in faces)
        reveals = sum(f.revealAreaM2 for f in faces)
        tiling_area = sum(f.tilingAreaM2 or 0 for f in faces) if tiling_h is not None else None
        paint = net_walls - (tiling_area or 0) + reveals + floor
        mrr = net.minimum_rotated_rectangle
        mc = list(mrr.exterior.coords) if isinstance(mrr, Polygon) else []
        dims = sorted([math.dist(mc[0], mc[1]), math.dist(mc[1], mc[2])]) if len(mc) >= 3 else [0.0, 0.0]

        room_wall_ids = sorted({f.wallId for f in faces if f.wallId} | set(wall_ids))
        def _src(w):
            return solved.wall_meta.get(w, {}).get("lengthSource", "MEASURED")
        estimated = [w for w in room_wall_ids if _src(w) == "SKETCH"]
        calculated = [w for w in room_wall_ids if _src(w) == "CALCULATED"]
        errs = [solved.wall_meta[w].get("lengthErrorMm", 0.0) for w in room_wall_ids if w in solved.wall_meta and wall_by_id[w].measured]
        out = [w for w in room_wall_ids if w in solved.wall_meta and not solved.wall_meta[w].get("withinTolerance", True)]
        questions = []
        for w in room_wall_ids:
            if w in suspects:
                s = suspects[w]
                questions.append(
                    f"Parete {w}: misurata {s['declaredLengthMm'] / 10:.1f} cm, dal resto del rilievo risulta "
                    f"{s['suggestedLengthMm'] / 10:.1f} cm. Puoi ricontrollarla?"
                )
        if out and not any(w in suspects for w in out):
            questions.append(f"Le misure delle pareti {', '.join(out)} non chiudono: serve una diagonale o un ricontrollo.")
        for w in estimated:
            calc_mm = solved.wall_meta[w].get("calculatedLengthMm", wall_by_id[w].length_mm)
            questions.append(f"Parete {w}: non misurata e non ricavabile dalle altre misure, stimata {calc_mm / 10:.0f} cm dallo schizzo. Serve la misura.")
        loose = sorted({w for w in room_wall_ids if w in undetermined_by_wall})
        for w in loose:
            host = undetermined_by_wall[w][0]["hostWallId"]
            questions.append(f"Posizione del tramezzo {w} lungo la parete {host} presa dallo schizzo: misura la distanza da un angolo.")
        free_walls = [w for w in room_wall_ids if w in solved.sketch_shape_walls]
        if free_walls:
            questions.append(f"Pareti oblique {', '.join(free_walls)}: la forma non è ricavabile dalle misure, aggiungi una diagonale.")

        confidence = 1.0
        confidence -= 0.25 * (len(estimated) / max(1, len(room_wall_ids)))
        confidence -= 0.3 if out else 0.0
        confidence -= 0.1 if loose else 0.0
        confidence -= 0.1 if free_walls else 0.0
        confidence = round(max(0.05, min(1.0, confidence)), 2)

        if out:
            quality = QualityStatus.NEEDS_REVIEW
        elif estimated or loose or free_walls:
            quality = QualityStatus.ESTIMATED
        else:
            quality = QualityStatus.OK

        coords = list(orient(net, 1.0).exterior.coords)[:-1]
        rooms.append(RoomModel(
            roomId=room_id, name=name, type=room_type,
            polygon=[PointMM(x=0.0 if abs(x) < 1e-6 else round(float(x), 3), y=0.0 if abs(y) < 1e-6 else round(float(y), 3)) for x, y in coords],
            wallIds=wall_ids, floorAreaM2=round(floor, 4), grossFloorAreaM2=round(gross.area / 1e6, 4),
            ceilingAreaM2=round(floor, 4), perimeterM=round(perimeter, 4),
            grossWallAreaM2=round(gross_walls, 4), quality=quality,
            heightMm=height_mm, heightSource=height_src, volumeM3=round(floor * height_mm / 1000, 3),
            widthM=round(dims[0] / 1000, 3), depthM=round(dims[1] / 1000, 3),
            skirtingM=round(max(0.0, perimeter - door_width_total / 1000), 3),
            openingsAreaM2=round(openings_area, 4), netWallAreaM2=round(net_walls, 4), revealsAreaM2=round(reveals, 4),
            tilingHeightMm=tiling_h, tilingAreaM2=round(tiling_area, 4) if tiling_area is not None else None,
            paintAreaM2=round(paint, 4), wallFaces=faces, openings=room_openings,
            estimatedWallIds=estimated, calculatedWallIds=calculated, maxWallErrorMm=round(max(errs, default=0.0), 1),
            confidence=confidence, questions=questions,
        ))

    # adiacenze e collegamenti tramite porte
    for room in rooms:
        mine = {f.wallId for f in room.wallFaces if f.wallId}
        room.adjacentRoomIds = sorted(
            other.roomId for other in rooms
            if other is not room and mine & {f.wallId for f in other.wallFaces if f.wallId} & shared_walls
        )
        for op in room.openings:
            other = next((r for r in rooms if r is not room and any(o.id == op.id for o in r.openings)), None)
            op.connectsToRoomId = other.roomId if other else None
    return rooms
