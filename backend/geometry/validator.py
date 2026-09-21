from __future__ import annotations
import math
from typing import Any
from shapely.geometry import LineString
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult, acceptance_mm
from backend.models import RoomModel


def validate_geometry(plan: NormalizedPlan, solved: SolverResult, rooms: list[RoomModel], *,
                      length_tolerance_mm: float = 0.5) -> dict[str, Any]:
    """Controllo finale. Un lato è "buono" se lo scarto è entro la tolleranza di rilievo
    calcolata dal solver (max(1 cm; 0,5% L) di default), non entro frazioni di millimetro."""
    wall_errors = []
    errors: list[str] = []
    warnings = list(solved.warnings)
    solved_lines = []
    for wall in plan.walls:
        a = solved.node_positions[wall.start_node]
        b = solved.node_positions[wall.end_node]
        calc = math.hypot(b[0] - a[0], b[1] - a[1])
        err = abs(calc - wall.length_mm)
        meta = solved.wall_meta.get(wall.id, {})
        tol = meta.get("toleranceMm") or acceptance_mm(wall.length_mm, 10.0, 0.005)
        within = err <= tol if wall.measured else True
        resolved_by = meta.get("resolvedBy")
        wall_errors.append({
            "wallId": wall.id, "declaredLengthMm": wall.length_mm, "sourceLengthCm": wall.source_length_cm,
            "calculatedLengthMm": calc, "errorMm": err, "toleranceMm": tol, "measured": wall.measured,
            "withinTolerance": within, "suspect": bool(meta.get("suspect")),
            "resolvedBy": resolved_by, "usedLengthMm": meta.get("usedLengthMm"),
        })
        solved_lines.append((wall.id, LineString([a, b])))
    measured_errors = [x["errorMm"] for x in wall_errors if x["measured"]]
    max_error = max(measured_errors, default=0.0)
    # fuori tolleranza ma spiegato da una decisione autonoma = risolto, non un errore
    bad = [x["wallId"] for x in wall_errors if not x["withinTolerance"] and not x["resolvedBy"]]
    if bad:
        errors.append(f"misure fuori tolleranza non spiegate: {', '.join(bad)} (max {max_error:.1f} mm)")
    ignored = {d.get("diagonalId") for d in solved.decisions if d.get("kind") == "diagonal_outlier"}
    for d in solved.diagonal_meta:
        if not d["withinTolerance"] and d["id"] not in ignored:
            errors.append(f"diagonale {d['id']} incoerente: scarto {d['errorMm']:.1f} mm")
    for i, (ida, la) in enumerate(solved_lines):
        for idb, lb in solved_lines[i + 1:]:
            inter = la.intersection(lb)
            if inter.is_empty:
                continue
            if inter.geom_type not in {"Point", "MultiPoint"}:
                warnings.append(f"Overlapping wall geometry: {ida}/{idb}")
    if not rooms:
        warnings.append("No closed room could be detected")
    needs_review = solved.needs_review or bool(errors) or not rooms
    return {
        "valid": not errors, "needsReview": needs_review, "maxLengthErrorMm": max_error,
        "closureErrorCm": solved.closure_error_mm / 10.0, "walls": wall_errors,
        "diagonals": solved.diagonal_meta, "suspects": solved.suspects, "decisions": solved.decisions,
        "warnings": warnings, "errors": errors,
    }
