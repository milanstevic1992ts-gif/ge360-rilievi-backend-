from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any
import networkx as nx
import numpy as np
from scipy.optimize import least_squares
from backend.geometry.normalizer import NormalizedPlan, NormalizedWall
from backend.geometry.topology import TopologyResult

@dataclass
class SolverResult:
    node_positions: dict[str,tuple[float,float]]
    wall_meta: dict[str,dict[str,Any]]
    warnings: list[str]
    operations: list[dict[str,Any]]
    needs_review: bool
    closure_error_mm: float
    max_length_error_mm: float

def _angle(vx,vy): return math.atan2(vy,vx)
def _wrap_pi(v): return (v+math.pi)%(2*math.pi)-math.pi
def _angle_distance(a,b): return abs(_wrap_pi(a-b))

def _component_orthogonal_base(walls:list[NormalizedWall], tolerance_deg:float):
    if len(walls)<3: return False,0.0,{}
    angles=[_angle(w.sketch_b[0]-w.sketch_a[0],w.sketch_b[1]-w.sketch_a[1]) for w in walls]
    c=sum(math.cos(4*a) for a in angles); s=sum(math.sin(4*a) for a in angles)
    base=math.atan2(s,c)/4.0 if abs(c)+abs(s)>1e-12 else angles[0]
    if abs(math.degrees(_wrap_pi(base)))<=12: base=0.0
    snapped={}; residuals=[]; axes=set()
    for wall,angle in zip(walls,angles):
        candidates=[base+k*math.pi/2 for k in range(-4,5)]
        chosen=min(candidates,key=lambda a:_angle_distance(a,angle)); residual=_angle_distance(chosen,angle)
        snapped[wall.id]=chosen; residuals.append(residual); axes.add(int(round((chosen-base)/(math.pi/2)))%2)
    ratio=sum(r<=math.radians(tolerance_deg) for r in residuals)/len(residuals)
    return ratio>=0.75 and len(axes)>=2, base, snapped

def _cycle_closure(graph:nx.MultiGraph,target_vectors:dict[str,tuple[float,float]])->float:
    simple=nx.Graph()
    for u,v,key,data in graph.edges(keys=True,data=True):
        if not simple.has_edge(u,v): simple.add_edge(u,v,wall_id=data["wall_id"])
    max_error=0.0
    for cycle in nx.cycle_basis(simple):
        sx=sy=0.0
        for i,u in enumerate(cycle):
            v=cycle[(i+1)%len(cycle)]; wid=simple.get_edge_data(u,v)["wall_id"]
            edge=next(d for _,_,_,d in graph.edges(keys=True,data=True) if d["wall_id"]==wid)
            sign=1.0 if (u==edge.get("start_node") and v==edge.get("end_node")) else -1.0
            tv=target_vectors[wid]; sx+=tv[0]*sign; sy+=tv[1]*sign
        max_error=max(max_error,math.hypot(sx,sy))
    return max_error

def solve_geometry(plan:NormalizedPlan, topology:TopologyResult, *, orthogonal_tolerance_deg:float=25.0,
                   length_tolerance_mm:float=0.5, angle_overrides:dict[str,float]|None=None)->SolverResult:
    graph=topology.graph.copy(); wall_by_id={w.id:w for w in plan.walls}
    for u,v,key,data in graph.edges(keys=True,data=True):
        w=wall_by_id[data["wall_id"]]; data["start_node"]=w.start_node; data["end_node"]=w.end_node
    node_ids=list(plan.nodes); index={n:i for i,n in enumerate(node_ids)}; scale=plan.scale_mm_per_unit
    min_x=min(n.sketch_x for n in plan.nodes.values()); min_y=min(n.sketch_y for n in plan.nodes.values())
    initial=np.zeros((len(node_ids),2),dtype=float)
    for node_id,node in plan.nodes.items():
        initial[index[node_id]]=[(node.sketch_x-min_x)*scale,(node.sketch_y-min_y)*scale]
    target_angles={}; wall_meta={}; operations=[]
    for comp in topology.components:
        comp_walls=[w for w in plan.walls if w.start_node in comp and w.end_node in comp]
        orthogonal,base,snapped=_component_orthogonal_base(comp_walls,orthogonal_tolerance_deg)
        if orthogonal: operations.append({"type":"orthogonal_component","nodes":sorted(comp),"baseAngleDeg":round(math.degrees(base),3)})
        for w in comp_walls:
            original=_angle(w.sketch_b[0]-w.sketch_a[0],w.sketch_b[1]-w.sketch_a[1]); chosen=snapped[w.id] if orthogonal else original
            target_angles[w.id]=chosen; wall_meta[w.id]={"originalAngleDeg":math.degrees(original),"targetAngleDeg":math.degrees(chosen),"orientation":"orthogonal" if orthogonal else "free"}
    for wid,ang in (angle_overrides or {}).items():
        if wid in target_angles:
            target_angles[wid]=float(ang); wall_meta[wid]["orientation"]="agent-constraint"; wall_meta[wid]["targetAngleDeg"]=math.degrees(float(ang))
    target_vectors={w.id:(w.length_mm*math.cos(target_angles[w.id]),w.length_mm*math.sin(target_angles[w.id])) for w in plan.walls}
    target_closure=_cycle_closure(graph,target_vectors); warnings=list(plan.warnings); needs_review=False
    if target_closure>max(2.0,length_tolerance_mm*4):
        needs_review=True; warnings.append(f"Authoritative lengths conflict with inferred angle constraints; closure mismatch {target_closure:.1f} mm")
    anchors=[]
    for comp in topology.components:
        first=min(comp,key=lambda n:index[n]); i=index[first]; anchors.append((i,initial[i,0],initial[i,1]))
    def residuals(flat):
        pts=flat.reshape((-1,2)); res=[]
        for w in plan.walls:
            a=pts[index[w.start_node]]; b=pts[index[w.end_node]]; d=b-a; length=float(np.hypot(d[0],d[1]))
            res.append((length-w.length_mm)/0.05)
            theta=target_angles[w.id]; tx,ty=w.length_mm*math.cos(theta),w.length_mm*math.sin(theta)
            sigma=6.0 if wall_meta[w.id]["orientation"]=="orthogonal" else 80.0
            res += [(d[0]-tx)/sigma,(d[1]-ty)/sigma]
        for i,ax,ay in anchors: res += [(pts[i,0]-ax)/0.5,(pts[i,1]-ay)/0.5]
        return np.asarray(res)
    opt=least_squares(residuals,initial.reshape(-1),method="trf",max_nfev=5000,xtol=1e-12,ftol=1e-12,gtol=1e-12)
    solved=opt.x.reshape((-1,2)); node_positions={nid:(float(solved[index[nid],0]),float(solved[index[nid],1])) for nid in node_ids}
    max_err=0.0
    for w in plan.walls:
        a=node_positions[w.start_node]; b=node_positions[w.end_node]; calc=math.hypot(b[0]-a[0],b[1]-a[1]); err=abs(calc-w.length_mm); max_err=max(max_err,err)
        theta=_angle(b[0]-a[0],b[1]-a[1]); wall_meta[w.id].update(calculatedLengthMm=calc,lengthErrorMm=err,solvedAngleDeg=math.degrees(theta),angleErrorDeg=math.degrees(_angle_distance(theta,target_angles[w.id])))
    if max_err>length_tolerance_mm: needs_review=True; warnings.append(f"Maximum authoritative length error is {max_err:.3f} mm")
    if not opt.success: needs_review=True; warnings.append(f"Geometry optimizer did not converge: {opt.message}")
    return SolverResult(node_positions,wall_meta,warnings,operations,needs_review,target_closure,max_err)
