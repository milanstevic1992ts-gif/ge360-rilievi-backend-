from __future__ import annotations

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult
from backend.models import PointMM, QualityStatus, RoomModel


def _boundary_wall_ids(poly: Polygon, lines: dict[str, LineString]) -> list[str]:
    boundary = poly.boundary
    result = []
    for wall_id, line in lines.items():
        if boundary.intersection(line).length > 1.0:
            result.append(wall_id)
    return sorted(result)


def _best_room_name(wall_ids: list[str], provided: list[dict], fallback: str) -> tuple[str, str | None]:
    got = set(wall_ids)
    best = None
    best_score = 0.0
    for room in provided:
        wanted = set(room.get("wallIds") or [])
        if not wanted:
            continue
        union = got | wanted
        score = len(got & wanted) / len(union) if union else 0.0
        if score > best_score:
            best_score = score
            best = room
    if best is not None and best_score >= 0.4:
        return best.get("name") or fallback, best.get("id")
    return fallback, None


def detect_rooms(plan: NormalizedPlan, solved: SolverResult) -> list[RoomModel]:
    wall_by_id = {w.id: w for w in plan.walls}
    lines: dict[str, LineString] = {}
    for w in plan.walls:
        a = solved.node_positions[w.start_node]
        b = solved.node_positions[w.end_node]
        lines[w.id] = LineString([a, b])

    linework = unary_union(list(lines.values()))
    polygons = [p for p in polygonize(linework) if p.area > 10_000]
    polygons.sort(key=lambda p: (round(p.centroid.y, 3), round(p.centroid.x, 3)))

    merged_estimated = max(plan.merged_gaps_mm, default=0) > 10.0
    rooms: list[RoomModel] = []
    for idx, poly in enumerate(polygons, start=1):
        wall_ids = _boundary_wall_ids(poly, lines)
        name, source_id = _best_room_name(wall_ids, plan.rooms, f"Ambiente {idx}")
        height_mm = max((wall_by_id[w].height_mm for w in wall_ids if w in wall_by_id), default=2700)
        perimeter_mm = sum(wall_by_id[w].length_mm for w in wall_ids if w in wall_by_id)
        quality = QualityStatus.NEEDS_REVIEW if solved.needs_review else (QualityStatus.ESTIMATED if merged_estimated else QualityStatus.OK)
        coords = list(poly.exterior.coords)[:-1]
        rooms.append(RoomModel(
            roomId=source_id or f"room-{idx}",
            name=name,
            polygon=[PointMM(x=float(x), y=float(y)) for x, y in coords],
            wallIds=wall_ids,
            floorAreaM2=poly.area / 1_000_000.0,
            ceilingAreaM2=poly.area / 1_000_000.0,
            perimeterM=perimeter_mm / 1000.0,
            grossWallAreaM2=perimeter_mm * height_mm / 1_000_000.0,
            quality=quality,
        ))
    return rooms
