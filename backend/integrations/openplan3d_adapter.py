from __future__ import annotations
from backend.models import PlanModel

def to_openplan3d(plan:PlanModel)->dict:
    # Adapter only: GE360 remains authoritative. Coordinates are converted mm->cm
    # because openPlan3D's editor/viewer commonly represents plan dimensions in cm.
    return {"source":"GE360","units":"cm","walls":[{"id":w.id,"start":{"x":w.start.x/10,"y":w.start.y/10},"end":{"x":w.end.x/10,"y":w.end.y/10},"height":w.heightMm/10,"thickness":w.thicknessMm/10} for w in plan.walls],"doors":[{"id":o.id,"wallId":o.wallId,"width":o.widthMm/10,"height":o.heightMm/10,"offset":o.offsetMm/10,"referenceEnd":o.referenceEnd} for o in plan.openings if o.type=="door"],"windows":[{"id":o.id,"wallId":o.wallId,"width":o.widthMm/10,"height":o.heightMm/10,"sillHeight":o.sillHeightMm/10,"offset":o.offsetMm/10,"referenceEnd":o.referenceEnd} for o in plan.openings if o.type=="window"],"rooms":[{"id":r.roomId,"name":r.name,"polygon":[{"x":p.x/10,"y":p.y/10} for p in r.polygon]} for r in plan.rooms]}
