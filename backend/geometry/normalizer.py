from __future__ import annotations
import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any
from backend.models import PlanPayload

@dataclass
class NormalizedNode:
    id: str
    sketch_x: float
    sketch_y: float
    source_endpoints: list[tuple[str, str]] = field(default_factory=list)

@dataclass
class NormalizedWall:
    id: str
    start_node: str
    end_node: str
    sketch_a: tuple[float, float]
    sketch_b: tuple[float, float]
    length_mm: float
    source_length_cm: float
    thickness_mm: float
    height_mm: float
    raw: dict[str, Any]

@dataclass
class NormalizedPlan:
    plan_id: str
    name: str
    nodes: dict[str, NormalizedNode]
    walls: list[NormalizedWall]
    openings: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    notes: list[Any]
    scale_mm_per_unit: float
    merged_gaps_mm: list[float]
    warnings: list[str]
    raw_payload: dict[str, Any]

class _UnionFind:
    def __init__(self, n: int):
        self.parent=list(range(n)); self.rank=[0]*n
    def find(self,x:int)->int:
        while self.parent[x]!=x:
            self.parent[x]=self.parent[self.parent[x]]; x=self.parent[x]
        return x
    def union(self,a:int,b:int)->None:
        ra,rb=self.find(a),self.find(b)
        if ra==rb: return
        if self.rank[ra]<self.rank[rb]: ra,rb=rb,ra
        self.parent[rb]=ra
        if self.rank[ra]==self.rank[rb]: self.rank[ra]+=1

def _distance(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])

def normalize_payload(payload: PlanPayload, *, default_thickness_mm: float=120,
                      default_height_mm: float=2700, snap_tolerance_mm: float=250) -> NormalizedPlan:
    if not payload.walls: raise ValueError("plan has no walls")
    ratios=[]
    for wall in payload.walls:
        if wall.lengthCm is None: continue
        d=math.hypot(wall.b.x-wall.a.x, wall.b.y-wall.a.y)
        if d>1e-9: ratios.append(wall.lengthCm*10.0/d)
    if not ratios: raise ValueError("at least one measured wall is required")
    scale=median(ratios)
    if not math.isfinite(scale) or scale<=0: raise ValueError("invalid sketch scale")

    endpoints=[]
    for wi,wall in enumerate(payload.walls):
        endpoints += [
            {"wall_index":wi,"wall_id":wall.id,"end":"a","p":(wall.a.x,wall.a.y)},
            {"wall_index":wi,"wall_id":wall.id,"end":"b","p":(wall.b.x,wall.b.y)},
        ]
    uf=_UnionFind(len(endpoints)); threshold_units=snap_tolerance_mm/scale
    for i in range(len(endpoints)):
        for j in range(i+1,len(endpoints)):
            if endpoints[i]["wall_index"]==endpoints[j]["wall_index"]: continue
            if _distance(endpoints[i]["p"],endpoints[j]["p"])<=threshold_units: uf.union(i,j)
    groups={}
    for i in range(len(endpoints)): groups.setdefault(uf.find(i),[]).append(i)
    node_for_endpoint={}; nodes={}; merged_gaps=[]
    for idx,members in enumerate(groups.values(),start=1):
        x=sum(endpoints[i]["p"][0] for i in members)/len(members)
        y=sum(endpoints[i]["p"][1] for i in members)/len(members)
        node_id=f"n{idx}"; src=[]
        if len(members)>1:
            pts=[endpoints[i]["p"] for i in members]
            merged_gaps.append(max(_distance(a,b) for a in pts for b in pts)*scale)
        for i in members:
            key=(endpoints[i]["wall_id"], endpoints[i]["end"]); node_for_endpoint[key]=node_id; src.append(key)
        nodes[node_id]=NormalizedNode(node_id,x,y,src)

    warnings=[]; walls=[]
    plan_height=payload.wallHeightM*1000 if payload.wallHeightM>0 else default_height_mm
    for wall in payload.walls:
        if wall.lengthCm is None: raise ValueError(f"wall {wall.id} has no authoritative lengthCm")
        s=node_for_endpoint[(wall.id,"a")]; e=node_for_endpoint[(wall.id,"b")]
        if s==e: warnings.append(f"Wall {wall.id}: endpoints collapsed into the same topology node")
        walls.append(NormalizedWall(
            id=wall.id,start_node=s,end_node=e,
            sketch_a=(wall.a.x,wall.a.y),sketch_b=(wall.b.x,wall.b.y),
            length_mm=wall.lengthCm*10.0,source_length_cm=wall.lengthCm,
            thickness_mm=wall.thicknessMm or default_thickness_mm,
            height_mm=wall.heightMm or plan_height,raw=wall.model_dump(mode="json")
        ))
    return NormalizedPlan(
        plan_id=payload.planId,name=payload.name,nodes=nodes,walls=walls,
        openings=[o.model_dump(mode="json") for o in payload.openings],
        rooms=[r.model_dump(mode="json") for r in payload.rooms],notes=list(payload.notes),
        scale_mm_per_unit=scale,merged_gaps_mm=merged_gaps,warnings=warnings,
        raw_payload=payload.model_dump(mode="json"),
    )
