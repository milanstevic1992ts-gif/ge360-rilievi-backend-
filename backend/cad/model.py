from __future__ import annotations
import math
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.rooms import detect_rooms
from backend.geometry.solver import SolverResult
from backend.models import ConstraintKind, ConstraintModel, NodeModel, OpeningModel, PlanModel, PointMM, WallModel

def _clean(v:float)->float:
    v=round(float(v),6)
    return 0.0 if abs(v)<1e-6 else v

def build_cad_model(plan:NormalizedPlan,solved:SolverResult)->PlanModel:
    rooms=detect_rooms(plan,solved); warnings=list(solved.warnings); needs_review=solved.needs_review
    nodes=[NodeModel(id=nid,point=PointMM(x=_clean(solved.node_positions[nid][0]),y=_clean(solved.node_positions[nid][1])),sourceEndpoints=node.source_endpoints) for nid,node in plan.nodes.items()]
    walls=[]; wall_map={w.id:w for w in plan.walls}
    for wall in plan.walls:
        a=solved.node_positions[wall.start_node]; b=solved.node_positions[wall.end_node]; calc=math.hypot(b[0]-a[0],b[1]-a[1])
        walls.append(WallModel(id=wall.id,startNodeId=wall.start_node,endNodeId=wall.end_node,start=PointMM(x=_clean(a[0]),y=_clean(a[1])),end=PointMM(x=_clean(b[0]),y=_clean(b[1])),declaredLengthMm=wall.length_mm,calculatedLengthMm=calc,sourceLengthCm=wall.source_length_cm,heightMm=wall.height_mm,thicknessMm=wall.thickness_mm,sourceStroke={"strokeId":wall.raw.get("strokeId"),"a":{"x":wall.sketch_a[0],"y":wall.sketch_a[1]},"b":{"x":wall.sketch_b[0],"y":wall.sketch_b[1]}},quality="NEEDS_REVIEW" if abs(calc-wall.length_mm)>0.5 else "OK",orientation=solved.wall_meta[wall.id]["orientation"]))
    openings=[]
    for raw in plan.openings:
        wall=wall_map.get(raw.get("wallId"))
        if wall is None: warnings.append(f"Opening {raw.get('id')}: wall not found"); needs_review=True; continue
        width_mm=float(raw.get("widthCm") or 0)*10
        if width_mm<=0: warnings.append(f"Opening {raw.get('id')}: missing widthCm"); needs_review=True; continue
        reference=raw.get("referenceEnd") if raw.get("referenceEnd") in {"a","b"} else "a"; offset_cm=raw.get("offsetCm")
        if offset_cm is None:
            pos=raw.get("position")
            if pos is None: warnings.append(f"Opening {raw.get('id')}: missing offsetCm and position"); needs_review=True; continue
            center_from_a=max(0,min(1,float(pos)))*wall.length_mm; offset_mm=center_from_a-width_mm/2 if reference=="a" else wall.length_mm-center_from_a-width_mm/2
            warnings.append(f"Opening {raw.get('id')}: offset inferred from sketch position")
        else:
            offset_mm=float(offset_cm)*10; center_from_a=offset_mm+width_mm/2 if reference=="a" else wall.length_mm-offset_mm-width_mm/2
        if offset_mm<-1e-6 or offset_mm+width_mm>wall.length_mm+1e-6: warnings.append(f"Opening {raw.get('id')}: width/offset does not fit wall"); needs_review=True
        a=solved.node_positions[wall.start_node]; b=solved.node_positions[wall.end_node]; dx,dy=b[0]-a[0],b[1]-a[1]; gl=math.hypot(dx,dy) or 1; ux,uy=dx/gl,dy/gl; cx,cy=a[0]+ux*center_from_a,a[1]+uy*center_from_a
        if raw.get("heightMm") is not None: height_mm,hsrc=float(raw["heightMm"]),"USER_MM"
        elif raw.get("heightCm") is not None: height_mm,hsrc=float(raw["heightCm"])*10,"USER_CM"
        else: height_mm,hsrc=(2100.0 if raw.get("type")=="door" else 1200.0),"DEFAULT"
        if raw.get("sillHeightMm") is not None: sill,ssrc=float(raw["sillHeightMm"]),"USER_MM"
        elif raw.get("sillHeightCm") is not None: sill,ssrc=float(raw["sillHeightCm"])*10,"USER_CM"
        else: sill,ssrc=(0.0 if raw.get("type")=="door" else 900.0),"DEFAULT"
        openings.append(OpeningModel(id=str(raw.get("id")),type=raw.get("type","door"),wallId=wall.id,widthMm=width_mm,heightMm=height_mm,offsetMm=offset_mm,referenceEnd=reference,sillHeightMm=sill,centerFromStartMm=center_from_a,center=PointMM(x=_clean(cx),y=_clean(cy)),heightSource=hsrc,sillHeightSource=ssrc))
    constraints=[]
    for idx,op in enumerate(solved.operations,1):
        if op.get("type")=="orthogonal_component": constraints.append(ConstraintModel(id=f"solver-{idx}",kind=ConstraintKind.PERPENDICULAR,nodeIds=op.get("nodes",[]),metadata=op))
    return PlanModel(planId=plan.plan_id,name=plan.name,nodes=nodes,walls=walls,openings=openings,rooms=rooms,constraints=constraints,notes=plan.notes,warnings=warnings,needsReview=needs_review,metadata={"sourceVersion":plan.raw_payload.get("version",4),"scaleMmPerSketchUnit":plan.scale_mm_per_unit,"mergedEndpointMaxGapMm":max(plan.merged_gaps_mm,default=0.0),"solverOperations":solved.operations})
