from __future__ import annotations
import math
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.rooms import detect_rooms
from backend.geometry.solver import SolverResult
from backend.models import ConstraintKind, ConstraintModel, NodeModel, OpeningModel, PlanModel, PointMM, WallModel

def _clean(v:float)->float:
    v=round(float(v),6)
    return 0.0 if abs(v)<1e-6 else v

def build_cad_model(plan:NormalizedPlan,solved:SolverResult,*,bath_tiling_height_mm:float=2200.0,room_hints:dict|None=None,uncertainty_samples:int=0)->PlanModel:
    warnings=list(solved.warnings); needs_review=solved.needs_review
    nodes=[NodeModel(id=nid,point=PointMM(x=_clean(solved.node_positions[nid][0]),y=_clean(solved.node_positions[nid][1])),sourceEndpoints=node.source_endpoints) for nid,node in plan.nodes.items()]
    walls=[]; wall_map={w.id:w for w in plan.walls}
    for wall in plan.walls:
        a=solved.node_positions[wall.start_node]; b=solved.node_positions[wall.end_node]; calc=math.hypot(b[0]-a[0],b[1]-a[1])
        meta=solved.wall_meta.get(wall.id,{})
        within=bool(meta.get("withinTolerance",True))
        source=meta.get("lengthSource","MEASURED" if wall.measured else "SKETCH")
        quality="NEEDS_REVIEW" if not within else {"MEASURED":"OK","CALCULATED":"CALCULATED","SUSPECT_MEASURED":"NEEDS_REVIEW"}.get(source,"ESTIMATED")
        construction_state=wall.raw.get("constructionState") if wall.raw.get("constructionState") in {"existing","demolish","new","close-opening","new-opening"} else "existing"
        construction_thickness_cm=wall.raw.get("constructionThicknessCm")
        construction_thickness_mm=(float(construction_thickness_cm)*10.0) if construction_thickness_cm not in (None,"") else None
        walls.append(WallModel(id=wall.id,startNodeId=wall.start_node,endNodeId=wall.end_node,start=PointMM(x=_clean(a[0]),y=_clean(a[1])),end=PointMM(x=_clean(b[0]),y=_clean(b[1])),declaredLengthMm=wall.length_mm if wall.measured else round(calc,1),calculatedLengthMm=calc,sourceLengthCm=wall.source_length_cm,heightMm=wall.height_mm,thicknessMm=wall.thickness_mm,sourceStroke={"strokeId":wall.raw.get("strokeId"),"a":{"x":wall.sketch_a[0],"y":wall.sketch_a[1]},"b":{"x":wall.sketch_b[0],"y":wall.sketch_b[1]}},quality=quality,orientation=meta.get("orientation","free"),measured=wall.measured,lengthErrorMm=round(abs(calc-wall.length_mm),3),toleranceMm=round(float(meta.get("toleranceMm",0.0)),3),withinTolerance=within,suspect=bool(meta.get("suspect")),suggestedLengthMm=meta.get("suggestedLengthMm"),lengthSource=source,resolvedBy=meta.get("resolvedBy"),usedLengthMm=meta.get("usedLengthMm"),constructionState=construction_state,constructionThicknessMm=construction_thickness_mm))
    openings=[]
    for raw in plan.openings:
        wall=wall_map.get(raw.get("wallId"))
        if wall is None: warnings.append(f"Opening {raw.get('id')}: wall not found"); needs_review=True; continue
        width_mm=float(raw.get("widthCm") or 0)*10
        if width_mm<=0: warnings.append(f"Opening {raw.get('id')}: missing widthCm"); needs_review=True; continue
        reference=raw.get("referenceEnd") if raw.get("referenceEnd") in {"a","b"} else "a"; offset_cm=raw.get("offsetCm")
        a=solved.node_positions[wall.start_node]; b=solved.node_positions[wall.end_node]
        dx,dy=b[0]-a[0],b[1]-a[1]; gl=math.hypot(dx,dy) or 1.0
        if offset_cm is None:
            pos=raw.get("position")
            if pos is None: warnings.append(f"Opening {raw.get('id')}: missing offsetCm and position"); needs_review=True; continue
            center_from_a=max(0,min(1,float(pos)))*gl
            offset_mm=center_from_a-width_mm/2 if reference=="a" else gl-center_from_a-width_mm/2
            warnings.append(f"Opening {raw.get('id')}: offset inferred from sketch position")
        else:
            offset_mm=float(offset_cm)*10
            center_from_a=offset_mm+width_mm/2 if reference=="a" else gl-offset_mm-width_mm/2
        if offset_mm<-1e-6 or offset_mm+width_mm>gl+1e-6: warnings.append(f"Opening {raw.get('id')}: width/offset does not fit solved wall"); needs_review=True
        ux,uy=dx/gl,dy/gl; cx,cy=a[0]+ux*center_from_a,a[1]+uy*center_from_a
        if raw.get("heightMm") is not None: height_mm,hsrc=float(raw["heightMm"]),"USER_MM"
        elif raw.get("heightCm") is not None: height_mm,hsrc=float(raw["heightCm"])*10,"USER_CM"
        else: height_mm,hsrc=(2100.0 if raw.get("type")=="door" else 1200.0),"DEFAULT"
        if raw.get("sillHeightMm") is not None: sill,ssrc=float(raw["sillHeightMm"]),"USER_MM"
        elif raw.get("sillHeightCm") is not None: sill,ssrc=float(raw["sillHeightCm"])*10,"USER_CM"
        else: sill,ssrc=(0.0 if raw.get("type")=="door" else 900.0),"DEFAULT"
        opening_type=raw.get("type","door")
        door_kind=raw.get("doorKind") if raw.get("doorKind") in {"internal","double","sliding","armored","armored-double"} else ("internal" if opening_type=="door" else None)
        window_kind=raw.get("windowKind") if raw.get("windowKind") in {"single","double","triple","sliding","balcony","balcony-double"} else ("single" if opening_type=="window" else None)
        leaves_raw=raw.get("leaves")
        leaves=int(leaves_raw) if isinstance(leaves_raw,(int,float)) and int(leaves_raw)>0 else (2 if door_kind in {"double","armored-double"} or window_kind in {"double","sliding","balcony-double"} else (3 if window_kind=="triple" else 1))
        armored=bool(raw.get("armored") or door_kind in {"armored","armored-double"})
        sliding=bool(raw.get("sliding") or door_kind=="sliding" or window_kind=="sliding")
        balcony=bool(raw.get("balconyDoor") or window_kind in {"balcony","balcony-double"})
        hinge_end=raw.get("hingeEnd") if raw.get("hingeEnd") in {"a","b"} else None
        swing_direction=raw.get("swingDirection") if raw.get("swingDirection") in {"inward","outward"} else None
        swing_side=-1 if raw.get("swingSide")==-1 else (1 if raw.get("swingSide")==1 else None)
        slide_to=raw.get("slideTo") if raw.get("slideTo") in {"a","b"} else None
        openings.append(OpeningModel(id=str(raw.get("id")),type=opening_type,wallId=wall.id,widthMm=width_mm,heightMm=height_mm,offsetMm=offset_mm,referenceEnd=reference,sillHeightMm=sill,centerFromStartMm=center_from_a,center=PointMM(x=_clean(cx),y=_clean(cy)),heightSource=hsrc,sillHeightSource=ssrc,doorKind=door_kind,windowKind=window_kind,category=raw.get("category"),leaves=leaves,sliding=sliding,armored=armored,balconyDoor=balcony,hingeEnd=hinge_end,swingDirection=swing_direction,swingSide=swing_side,slideTo=slide_to))
    rooms=detect_rooms(plan,solved,openings,bath_tiling_height_mm=bath_tiling_height_mm,room_hints=room_hints)
    uncertainty={}
    if uncertainty_samples>0 and rooms:
        from backend.geometry.uncertainty import room_area_uncertainty
        uncertainty=room_area_uncertainty(plan,solved,rooms,samples=uncertainty_samples)
        for room in rooms:
            st=(uncertainty.get("rooms") or {}).get(room.roomId)
            if not st:continue
            room.floorAreaRangeM2=[st["p10"],st["p90"]];room.floorAreaStdM2=st["std"]
            rel=st["std"]/room.floorAreaM2 if room.floorAreaM2>0 else 0.0
            room.confidence=round(max(0.05,room.confidence*max(0.3,1.0-4.0*rel)),2)
    constraints=[]
    for idx,op in enumerate(solved.operations,1):
        if op.get("type")=="orthogonal_component": constraints.append(ConstraintModel(id=f"solver-{idx}",kind=ConstraintKind.PERPENDICULAR,nodeIds=op.get("nodes",[]),metadata=op))
    raw = plan.raw_payload
    document_meta = {
        "client": raw.get("client") or raw.get("cliente") or raw.get("customerName"),
        "address": raw.get("address") or raw.get("indirizzo") or raw.get("siteAddress"),
        "surveyDate": raw.get("surveyDate") or raw.get("sopralluogoAt") or raw.get("updatedAt"),
        "reference": raw.get("reference") or raw.get("surveyReference") or raw.get("rilievoRef") or plan.plan_id,
        "linkedQuote": raw.get("linkedQuote") or raw.get("preventivoCollegato"),
        "unitLabel": raw.get("unitLabel") or raw.get("floorLabel") or raw.get("piano"),
        "northAngleDeg": raw.get("northAngleDeg"),
        "whatsappUrl": raw.get("whatsappUrl"),
        "siteUrl": raw.get("siteUrl"),
    }
    document_meta = {key: value for key, value in document_meta.items() if value not in (None, "")}

    return PlanModel(
        technicalSchema=str(plan.raw_payload.get("technicalSchema") or "ge360-technical-plan-v1"),
        planId=plan.plan_id,
        name=plan.name,
        nodes=nodes,
        walls=walls,
        openings=openings,
        rooms=rooms,
        constraints=constraints,
        notes=plan.notes,
        warnings=warnings,
        needsReview=needs_review,
        metadata={
            "sourceVersion": plan.raw_payload.get("version", 4),
            "technicalSchema": plan.raw_payload.get("technicalSchema") or "ge360-technical-plan-v1",
            "scaleMmPerSketchUnit": plan.scale_mm_per_unit,
            "mergedEndpointMaxGapMm": max(plan.merged_gaps_mm, default=0.0),
            "solverOperations": solved.operations,
            "decisions": solved.decisions,
            "uncertainty": uncertainty,
            "wallReference": plan.wall_reference,
            "baseAngleDeg": solved.base_angle_deg,
            "suspects": solved.suspects,
            "diagonals": solved.diagonal_meta,
            "closedGaps": plan.closed_gaps,
            "tJunctions": plan.tees,
            "document": document_meta,
        },
    )
