from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from backend.models import PlanModel

@dataclass
class ArchitSnapshot:
    walls: list[Any]
    room_polygons: list[Any]

def available()->bool:
    try: import archit_app  # noqa
    except Exception:return False
    return True

def to_archit(plan:PlanModel)->ArchitSnapshot:
    try:
        from archit_app import Point2D, Polygon2D, Wall, WORLD
    except ImportError as exc:
        raise RuntimeError("archit-app is not installed; install archit-app>=0.7,<0.8") from exc
    walls=[]
    for w in plan.walls:
        wall=Wall.straight(w.start.x/1000,w.start.y/1000,w.end.x/1000,w.end.y/1000,thickness=w.thicknessMm/1000,height=w.heightMm/1000)
        if abs(wall.length-w.declaredLengthMm/1000)>1e-6: raise ValueError(f"archit-app changed authoritative wall length for {w.id}")
        walls.append(wall)
    polys=[]
    for room in plan.rooms:
        polys.append(Polygon2D(exterior=tuple(Point2D(x=p.x/1000,y=p.y/1000,crs=WORLD) for p in room.polygon),crs=WORLD))
    return ArchitSnapshot(walls=walls,room_polygons=polys)

def validate_roundtrip(plan:PlanModel)->dict:
    snap=to_archit(plan); areas=[p.area for p in snap.room_polygons]
    return {"available":True,"walls":len(snap.walls),"rooms":len(areas),"roomAreasM2":areas}
