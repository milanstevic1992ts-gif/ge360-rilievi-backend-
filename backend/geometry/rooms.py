from __future__ import annotations
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult
from backend.models import PointMM, QualityStatus, RoomModel

def _boundary_wall_ids(poly:Polygon,lines:dict[str,LineString])->list[str]:
    boundary=poly.boundary; result=[]
    for wid,line in lines.items():
        if boundary.intersection(line).length>1.0: result.append(wid)
    return sorted(result)

def _best_room_name(wall_ids,provided,fallback):
    got=set(wall_ids); best=None; best_score=0.0
    for room in provided:
        wanted=set(room.get("wallIds") or [])
        if not wanted: continue
        union=got|wanted; score=len(got&wanted)/len(union) if union else 0
        if score>best_score: best_score=score; best=room
    if best is not None and best_score>=0.4: return best.get("name") or fallback,best.get("id")
    return fallback,None

def detect_rooms(plan:NormalizedPlan,solved:SolverResult)->list[RoomModel]:
    wall_by_id={w.id:w for w in plan.walls}; lines={}
    for w in plan.walls:
        lines[w.id]=LineString([solved.node_positions[w.start_node],solved.node_positions[w.end_node]])
    polygons=[p for p in polygonize(unary_union(list(lines.values()))) if p.area>10_000]
    polygons.sort(key=lambda p:(round(p.centroid.y,3),round(p.centroid.x,3)))
    merged_estimated=max(plan.merged_gaps_mm,default=0)>10.0; rooms=[]
    for idx,poly in enumerate(polygons,start=1):
        wall_ids=_boundary_wall_ids(poly,lines); name,source_id=_best_room_name(wall_ids,plan.rooms,f"Ambiente {idx}")
        height_mm=max((wall_by_id[w].height_mm for w in wall_ids if w in wall_by_id),default=2700)
        perimeter_mm=poly.length
        quality=QualityStatus.NEEDS_REVIEW if solved.needs_review else (QualityStatus.ESTIMATED if merged_estimated else QualityStatus.OK)
        coords=list(poly.exterior.coords)[:-1]
        rooms.append(RoomModel(roomId=source_id or f"room-{idx}",name=name,polygon=[PointMM(x=0.0 if abs(x)<1e-6 else round(float(x),6),y=0.0 if abs(y)<1e-6 else round(float(y),6)) for x,y in coords],wallIds=wall_ids,floorAreaM2=poly.area/1e6,ceilingAreaM2=poly.area/1e6,perimeterM=perimeter_mm/1000,grossWallAreaM2=perimeter_mm*height_mm/1e6,quality=quality))
    return rooms
