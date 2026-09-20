from __future__ import annotations

import math

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.rooms import detect_rooms
from backend.geometry.solver import SolverResult
from backend.models import OpeningModel, PlanModel, PointMM, WallModel


def build_cad_model(plan: NormalizedPlan, solved: SolverResult) -> PlanModel:
    rooms = detect_rooms(plan, solved)
    warnings = list(solved.warnings)
    needs_review = solved.needs_review
    walls: list[WallModel] = []
    wall_map = {w.id: w for w in plan.walls}
    for wall in plan.walls:
        a = solved.node_positions[wall.start_node]
        b = solved.node_positions[wall.end_node]
        calc = math.hypot(b[0] - a[0], b[1] - a[1])
        walls.append(WallModel(
            id=wall.id,
            startNodeId=wall.start_node,
            endNodeId=wall.end_node,
            start=PointMM(x=a[0], y=a[1]),
            end=PointMM(x=b[0], y=b[1]),
            lengthMm=wall.length_mm,
            calculatedLengthMm=calc,
            sourceLengthCm=wall.source_length_cm,
            heightMm=wall.height_mm,
            thicknessMm=wall.thickness_mm,
            sourceSketch={"a": {"x": wall.sketch_a[0], "y": wall.sketch_a[1]}, "b": {"x": wall.sketch_b[0], "y": wall.sketch_b[1]}},
            orientation=solved.wall_meta[wall.id]["orientation"],
        ))

    openings: list[OpeningModel] = []
    for raw in plan.openings:
        wall = wall_map.get(raw.get("wallId"))
        if wall is None:
            warnings.append(f"Opening {raw.get('id')}: wall {raw.get('wallId')} not found")
            needs_review = True
            continue
        width_mm = float(raw.get("widthCm") or 0) * 10.0
        if width_mm <= 0:
            warnings.append(f"Opening {raw.get('id')}: missing authoritative widthCm")
            needs_review = True
            continue
        reference = raw.get("referenceEnd") if raw.get("referenceEnd") in {"a", "b"} else "a"
        offset_cm = raw.get("offsetCm")
        if offset_cm is None:
            position = raw.get("position")
            if position is None:
                warnings.append(f"Opening {raw.get('id')}: missing offsetCm and position")
                needs_review = True
                continue
            center_from_a = max(0.0, min(1.0, float(position))) * wall.length_mm
            offset_mm = center_from_a - width_mm / 2 if reference == "a" else wall.length_mm - center_from_a - width_mm / 2
            warnings.append(f"Opening {raw.get('id')}: offset inferred from sketch position")
        else:
            offset_mm = float(offset_cm) * 10.0
            center_from_a = offset_mm + width_mm / 2 if reference == "a" else wall.length_mm - offset_mm - width_mm / 2

        if offset_mm < -1e-6 or offset_mm + width_mm > wall.length_mm + 1e-6:
            warnings.append(f"Opening {raw.get('id')}: width/offset does not fit on wall {wall.id}")
            needs_review = True
        center_from_a = max(0.0, min(wall.length_mm, center_from_a))
        a = solved.node_positions[wall.start_node]
        b = solved.node_positions[wall.end_node]
        dx, dy = b[0] - a[0], b[1] - a[1]
        geom_len = math.hypot(dx, dy) or 1.0
        ux, uy = dx / geom_len, dy / geom_len
        cx, cy = a[0] + ux * center_from_a, a[1] + uy * center_from_a

        if raw.get("heightMm") is not None:
            height_mm, h_source = float(raw["heightMm"]), "USER_MM"
        elif raw.get("heightCm") is not None:
            height_mm, h_source = float(raw["heightCm"]) * 10.0, "USER_CM"
        else:
            height_mm, h_source = (2100.0 if raw.get("type") == "door" else 1200.0), "DEFAULT"

        if raw.get("sillHeightMm") is not None:
            sill_mm, s_source = float(raw["sillHeightMm"]), "USER_MM"
        elif raw.get("sillHeightCm") is not None:
            sill_mm, s_source = float(raw["sillHeightCm"]) * 10.0, "USER_CM"
        else:
            sill_mm, s_source = (0.0 if raw.get("type") == "door" else 900.0), "DEFAULT"

        openings.append(OpeningModel(
            id=str(raw.get("id")),
            type=raw.get("type", "door"),
            wallId=wall.id,
            widthMm=width_mm,
            heightMm=height_mm,
            offsetMm=offset_mm,
            referenceEnd=reference,
            sillHeightMm=sill_mm,
            centerFromStartMm=center_from_a,
            center=PointMM(x=cx, y=cy),
            heightSource=h_source,
            sillHeightSource=s_source,
        ))

    return PlanModel(
        planId=plan.plan_id,
        name=plan.name,
        walls=walls,
        openings=openings,
        rooms=rooms,
        notes=plan.notes,
        warnings=warnings,
        needsReview=needs_review,
        metadata={
            "sourceVersion": plan.raw_payload.get("version", 4),
            "scaleMmPerSketchUnit": plan.scale_mm_per_unit,
            "mergedEndpointMaxGapMm": max(plan.merged_gaps_mm, default=0.0),
            "solverOperations": solved.operations,
        },
    )
