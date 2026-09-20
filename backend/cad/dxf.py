from __future__ import annotations

from pathlib import Path

import ezdxf

from backend.cad.renderer import point_along
from backend.models import PlanModel


def export_dxf(model: PlanModel, path: Path) -> None:
    doc = ezdxf.new("R2018")
    for name in ("WALLS", "DOORS", "WINDOWS", "ROOMS", "DIMENSIONS", "TEXT"):
        if name not in doc.layers:
            doc.layers.add(name)
    msp = doc.modelspace()
    wall_map = {w.id: w for w in model.walls}
    for w in model.walls:
        msp.add_line((w.start.x, w.start.y), (w.end.x, w.end.y), dxfattribs={"layer":"WALLS", "lineweight":50})
        mx=(w.start.x+w.end.x)/2; my=(w.start.y+w.end.y)/2
        txt=msp.add_text(f"{w.lengthMm/1000:.2f} m", height=120, dxfattribs={"layer":"DIMENSIONS"})
        txt.set_placement((mx,my))
    for o in model.openings:
        w=wall_map.get(o.wallId)
        if not w: continue
        p1=point_along(w,o.centerFromStartMm-o.widthMm/2)
        p2=point_along(w,o.centerFromStartMm+o.widthMm/2)
        layer="DOORS" if o.type=="door" else "WINDOWS"
        msp.add_line(p1,p2,dxfattribs={"layer":layer})
        t=msp.add_text(f"{o.type.upper()} {o.widthMm:.0f}", height=90, dxfattribs={"layer":layer})
        t.set_placement(((p1[0]+p2[0])/2,(p1[1]+p2[1])/2))
    for room in model.rooms:
        pts=[(p.x,p.y) for p in room.polygon]
        if pts:
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer":"ROOMS"})
            cx=sum(x for x,_ in pts)/len(pts); cy=sum(y for _,y in pts)/len(pts)
            text=msp.add_mtext(f"{room.name}\\P{room.floorAreaM2:.2f} m²", dxfattribs={"layer":"TEXT","char_height":120})
            text.set_location((cx,cy))
    doc.header["$INSUNITS"] = 4
    doc.saveas(path)
