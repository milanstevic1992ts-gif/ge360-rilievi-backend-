from __future__ import annotations
import json,math,re
from backend.storage import PlanStorage
from .schemas import TargetCandidate
from .semantic_graph import SemanticSceneGraph
_ID=re.compile(r"\b[A-Za-z][A-Za-z0-9_-]*\b")
def _len(w):
    a,b=w.get("start") or {},w.get("end") or {}
    declared=w.get("declaredLengthMm")
    if declared is not None:
        try:return float(declared)/1000
        except Exception:pass
    return math.hypot(float(b.get("x",0))-float(a.get("x",0)),float(b.get("y",0))-float(a.get("y",0)))/1000
def _orientation(w):
    a,b=w.get("start") or {},w.get("end") or {}; dx=abs(float(b.get("x",0))-float(a.get("x",0))); dy=abs(float(b.get("y",0))-float(a.get("y",0)))
    if dx>dy*2:return "horizontal"
    if dy>dx*2:return "vertical"
    return "diagonal"
class ResolutionResult:
    def __init__(self,candidates,unique_id=None):self.candidates=candidates;self.unique_id=unique_id
    @property
    def ambiguous(self): return bool(self.candidates and not self.unique_id)
class PlanContext:
    def __init__(self,storage:PlanStorage,plan_id:str):
        self.storage=storage;self.plan_id=plan_id;self.base=storage.plan_dir(plan_id)/"current";p=self.base/"processed-plan.json"
        if not p.exists():raise FileNotFoundError("process plan before CAD_PLANNER")
        self.plan=json.loads(p.read_text(encoding="utf-8"));m=self.base/"manifest.json";self.manifest=json.loads(m.read_text()) if m.exists() else {}
        self.walls={str(x["id"]):x for x in self.plan.get("walls",[])};self.openings={str(x["id"]):x for x in self.plan.get("openings",[])};self.rooms={str(x["roomId"]):x for x in self.plan.get("rooms",[])};self.constraints={str(x["id"]):x for x in self.plan.get("constraints",[])}
        self.scene_graph=SemanticSceneGraph(self.plan)
    @property
    def current_version(self):return int(self.manifest.get("version") or 0)
    def existing_ids(self):
        return set(self.walls)|set(self.openings)|set(self.rooms)|set(self.constraints)|{str(n.get("id")) for n in self.plan.get("nodes",[]) if n.get("id")}
    def explicitly_referenced_ids(self,s):return {x for x in _ID.findall(s) if x in self.existing_ids()}
    def _wall_summary(self,w):
        wid=str(w["id"]);rooms=[r.get("name") for r in self.rooms.values() if wid in [str(x) for x in r.get("wallIds",[])]];opens=[o["id"] for o in self.openings.values() if str(o.get("wallId"))==wid]
        return {"id":wid,"lengthM":round(_len(w),3),"orientation":_orientation(w),"rooms":[x for x in rooms if x],"openings":opens,"thicknessMm":w.get("thicknessMm"),"heightMm":w.get("heightMm"),"relations":self.scene_graph.relations_for(wid)}
    def semantic_summary(self):
        return {"plan":{"planId":self.plan_id,"name":self.plan.get("name"),"version":self.current_version,"needsReview":bool(self.plan.get("needsReview"))},"rooms":[{"id":str(r["roomId"]),"name":r.get("name"),"areaM2":r.get("floorAreaM2"),"wallIds":[str(x) for x in r.get("wallIds",[])]} for r in self.rooms.values()],"walls":[self._wall_summary(w) for w in self.walls.values()],"openings":[{"id":str(o["id"]),"type":o.get("type"),"wallId":str(o.get("wallId")),"widthMm":o.get("widthMm"),"offsetMm":o.get("offsetMm")} for o in self.openings.values()],"constraints":[{"id":str(c["id"]),"kind":c.get("kind"),"wallIds":[str(x) for x in c.get("wallIds",[])]} for c in self.constraints.values()],"sceneGraph":self.scene_graph.compact()}
    def resolve_wall(self,orientation=None,approx_length_m=None,room=None,side=None,near_opening_type=None):
        if not self.walls:return ResolutionResult([])
        xs=[(float(w["start"]["x"])+float(w["end"]["x"]))/2 for w in self.walls.values()];ys=[(float(w["start"]["y"])+float(w["end"]["y"]))/2 for w in self.walls.values()]
        minx,maxx,miny,maxy=min(xs),max(xs),min(ys),max(ys);scored=[]
        for w in self.walls.values():
            wid=str(w["id"]);score=0;weight=0;e={}
            if orientation:weight+=.22;score+=.22 if _orientation(w)==orientation else 0;e["orientation"]=_orientation(w)
            if approx_length_m:
                weight+=.34;sim=max(0,1-abs(_len(w)-float(approx_length_m))/max(float(approx_length_m)*.35,.35));score+=.34*sim;e["lengthM"]=round(_len(w),3)
            if room:
                weight+=.2;names=[str(r.get("name") or "") for r in self.rooms.values() if wid in [str(x) for x in r.get("wallIds",[])]];hit=any(str(room).casefold() in n.casefold() for n in names);score+=.2 if hit else 0;e["rooms"]=names
            if side:
                weight+=.12;cx=(float(w["start"]["x"])+float(w["end"]["x"]))/2;cy=(float(w["start"]["y"])+float(w["end"]["y"]))/2
                vals={"left":(maxx-cx)/max(maxx-minx,1),"right":(cx-minx)/max(maxx-minx,1),"top":(maxy-cy)/max(maxy-miny,1),"bottom":(cy-miny)/max(maxy-miny,1)};score+=.12*max(0,min(1,vals[side]))
            if near_opening_type:
                weight+=.12;hit=any(str(o.get("wallId"))==wid and o.get("type")==near_opening_type for o in self.openings.values());score+=.12 if hit else 0
            conf=score/weight if weight else .5;scored.append((conf,w,e))
        scored.sort(key=lambda x:x[0],reverse=True);c=[TargetCandidate(type="wall",id=str(w["id"]),confidence=round(conf,4),label=f"{_orientation(w)} {_len(w):.2f} m",evidence=e) for conf,w,e in scored[:8] if conf>=.25]
        unique=None
        if c:
            margin=c[0].confidence-(c[1].confidence if len(c)>1 else 0)
            if c[0].confidence>=.82 and (len(c)==1 or margin>=.12):unique=c[0].id
        return ResolutionResult(c,unique)
    def execute_read_tool(self,name,args):
        if name=="get_plan":return {"planId":self.plan_id,"version":self.current_version,"name":self.plan.get("name"),"needsReview":self.plan.get("needsReview")}
        if name=="get_plan_summary":return self.semantic_summary()
        if name=="get_wall":return self._wall_summary(self.walls[args["wall_id"]])
        if name=="get_walls":return {"walls":[x for x in (self._wall_summary(w) for w in self.walls.values()) if (not args.get("orientation") or x["orientation"]==args["orientation"]) and (not args.get("room") or any(args["room"].casefold() in str(n).casefold() for n in x["rooms"]))]}
        if name=="get_rooms":return {"rooms":[{"id":str(r["roomId"]),"name":r.get("name"),"areaM2":r.get("floorAreaM2"),"wallIds":[str(x) for x in r.get("wallIds",[])]} for r in self.rooms.values()]}
        if name=="get_room":
            if args.get("room_id"):r=self.rooms[args["room_id"]]
            else:
                ms=[r for r in self.rooms.values() if str(args.get("name") or "").casefold() in str(r.get("name") or "").casefold()]
                if not ms:raise ValueError("room not found")
                r=ms[0]
            return {"id":str(r["roomId"]),"name":r.get("name"),"areaM2":r.get("floorAreaM2"),"wallIds":[str(x) for x in r.get("wallIds",[])]}
        if name=="find_nearest_wall":
            rr=self.resolve_wall(**args);return {"resolvedWallId":rr.unique_id,"ambiguous":rr.ambiguous,"candidates":[x.model_dump(mode="json") for x in rr.candidates]}
        raise ValueError(f"read tool not implemented: {name}")
