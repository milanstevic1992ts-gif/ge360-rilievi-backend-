from __future__ import annotations
from pathlib import Path
import ezdxf
from backend.cad.renderer import point_along, wall_outline
from backend.models import PlanModel

LAYERS=("GE360_WALLS","GE360_DOORS","GE360_WINDOWS","GE360_ROOMS","GE360_DIMENSIONS","GE360_TEXT")
APPID="GE360"

def _tag(entity,*values):
    entity.set_xdata(APPID,[(1000,str(v)) for v in values])

def validate_dxf(path:Path)->dict:
    doc=ezdxf.readfile(path); auditor=doc.audit()
    missing=[name for name in LAYERS if name not in doc.layers]
    if missing: raise ValueError(f"DXF missing layers: {missing}")
    if auditor.has_errors: raise ValueError(f"DXF audit errors: {len(auditor.errors)}")
    msp=doc.modelspace(); return {"layers":list(LAYERS),"entities":len(msp),"units":int(doc.header.get("$INSUNITS",0))}

def export_dxf(model:PlanModel,path:Path)->dict:
    doc=ezdxf.new("R2018"); doc.appids.add(APPID)
    for name in LAYERS:
        if name not in doc.layers: doc.layers.add(name)
    doc.header["$INSUNITS"]=4; msp=doc.modelspace(); wall_map={w.id:w for w in model.walls}
    for w in model.walls:
        outline=msp.add_lwpolyline(wall_outline(w),close=True,dxfattribs={"layer":"GE360_WALLS"}); _tag(outline,"wall",w.id,f"lengthMm={w.declaredLengthMm:.6f}",f"thicknessMm={w.thicknessMm:.6f}")
        center=msp.add_line((w.start.x,w.start.y),(w.end.x,w.end.y),dxfattribs={"layer":"GE360_WALLS","lineweight":13}); _tag(center,"wall-centerline",w.id)
        mx=(w.start.x+w.end.x)/2; my=(w.start.y+w.end.y)/2; t=msp.add_text(f"{w.declaredLengthMm/1000:.2f} m",height=120,dxfattribs={"layer":"GE360_DIMENSIONS"}); t.set_placement((mx,my)); _tag(t,"dimension",w.id)
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w: continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2); p2=point_along(w,o.centerFromStartMm+o.widthMm/2); layer="GE360_DOORS" if o.type=="door" else "GE360_WINDOWS"
        ent=msp.add_line(p1,p2,dxfattribs={"layer":layer}); _tag(ent,o.type,o.id,f"wallId={o.wallId}",f"widthMm={o.widthMm:.6f}",f"offsetMm={o.offsetMm:.6f}",f"referenceEnd={o.referenceEnd}")
        txt=msp.add_text(f"{o.type.upper()} {o.widthMm:.0f}",height=90,dxfattribs={"layer":layer}); txt.set_placement(((p1[0]+p2[0])/2,(p1[1]+p2[1])/2))
    for room in model.rooms:
        pts=[(p.x,p.y) for p in room.polygon]
        if not pts: continue
        poly=msp.add_lwpolyline(pts,close=True,dxfattribs={"layer":"GE360_ROOMS"}); _tag(poly,"room",room.roomId,f"areaM2={room.floorAreaM2:.6f}")
        cx=sum(x for x,_ in pts)/len(pts); cy=sum(y for _,y in pts)/len(pts); mt=msp.add_mtext(f"{room.name}\\P{room.floorAreaM2:.2f} m²",dxfattribs={"layer":"GE360_TEXT","char_height":120}); mt.set_location((cx,cy)); _tag(mt,"room-text",room.roomId)
    doc.saveas(path); return validate_dxf(path)
