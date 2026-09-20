from __future__ import annotations
import math
from typing import Any
from shapely.geometry import LineString
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult
from backend.models import RoomModel

def validate_geometry(plan:NormalizedPlan,solved:SolverResult,rooms:list[RoomModel],*,length_tolerance_mm:float=0.5)->dict[str,Any]:
    wall_errors=[]; errors=[]; warnings=list(solved.warnings)
    solved_lines=[]
    for wall in plan.walls:
        a=solved.node_positions[wall.start_node]; b=solved.node_positions[wall.end_node]; calc=math.hypot(b[0]-a[0],b[1]-a[1]); err=abs(calc-wall.length_mm)
        wall_errors.append({"wallId":wall.id,"declaredLengthMm":wall.length_mm,"sourceLengthCm":wall.source_length_cm,"calculatedLengthMm":calc,"errorMm":err})
        solved_lines.append((wall.id,LineString([a,b])))
    max_error=max((x["errorMm"] for x in wall_errors),default=0.0)
    if max_error>length_tolerance_mm: errors.append(f"length preservation failed: max error {max_error:.3f} mm")
    for i,(ida,a) in enumerate(solved_lines):
        for idb,b in solved_lines[i+1:]:
            inter=a.intersection(b)
            if inter.is_empty: continue
            if inter.geom_type not in {"Point","MultiPoint"}: warnings.append(f"Overlapping wall geometry: {ida}/{idb}")
    if not rooms: warnings.append("No closed room could be detected")
    needs_review=solved.needs_review or bool(errors) or not rooms
    return {"valid":not errors,"needsReview":needs_review,"maxLengthErrorMm":max_error,"closureErrorCm":solved.closure_error_mm/10.0,"walls":wall_errors,"warnings":warnings,"errors":errors}
