from __future__ import annotations
import math
def source_angle_overrides(source,solved):
    out={}
    for wid,deg in (source.get("ge360AngleOverrides") or {}).items():
        if wid in solved.wall_meta:out[str(wid)]=math.radians(float(deg))
    for c in source.get("constraints",[]):
        kind=c.get("kind");wids=[str(x) for x in c.get("wallIds",[])]
        if kind not in {"parallel","perpendicular","collinear"} or len(wids)!=2:continue
        a,b=wids
        if a not in solved.wall_meta or b not in solved.wall_meta:continue
        base=math.radians(float(solved.wall_meta[a].get("solvedAngleDeg",solved.wall_meta[a].get("targetAngleDeg",0))))
        out[b]=base+(math.pi/2 if kind=="perpendicular" else 0)
    return out
