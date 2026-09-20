from __future__ import annotations
import copy,json,math,shutil,uuid
from datetime import datetime,timezone
from backend.cad import build_cad_model,export_dxf,export_pdf,export_png,export_svg
from backend.geometry.constraints import source_angle_overrides
from backend.geometry.normalizer import normalize_payload
from backend.geometry.score import geometry_score
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.geometry.validator import validate_geometry
from backend.models import PlanPayload,PlanStatus,QualityStatus
from backend.view3d import to_plan3d
from .context import PlanContext
from .schemas import CandidatePreview

class CandidateService:
    def __init__(self,settings,storage,db,audit,memory=None):self.settings=settings;self.storage=storage;self.db=db;self.audit=audit;self.memory=memory
    def _source(self,pid):
        p=self.storage.plan_dir(pid)/"current"/"source-plan.json"
        return json.loads(p.read_text()) if p.exists() else self.storage.raw_payload(pid)
    def _wall(self,s,i):
        w=next((x for x in s.get("walls",[]) if str(x.get("id"))==i),None)
        if not w:raise ValueError(f"wall not found: {i}")
        return w
    def _opening(self,s,i):
        o=next((x for x in s.get("openings",[]) if str(x.get("id"))==i),None)
        if not o:raise ValueError(f"opening not found: {i}")
        return o
    def _id(self,p):return f"{p}_ai_{uuid.uuid4().hex[:10]}"
    def _node_point(self,c,s,nid):
        n=next((x for x in c.plan.get("nodes",[]) if str(x.get("id"))==nid),None)
        if not n:raise ValueError("node not found")
        for ref in n.get("sourceEndpoints") or []:
            if len(ref)==2:
                try:
                    w=self._wall(s,str(ref[0]));p=w.get(str(ref[1]))
                    if isinstance(p,dict):return {"x":float(p["x"]),"y":float(p["y"])}
                except Exception:pass
        scale=float((c.plan.get("metadata") or {}).get("scaleMmPerSketchUnit") or 0);p=n.get("point") or {}
        if scale<=0:raise ValueError("cannot map node to source")
        return {"x":float(p.get("x",0))/scale,"y":float(p.get("y",0))/scale}
    def _connect(self,s,a,b):
        wa,wb=self._wall(s,a),self._wall(s,b);pairs=[]
        for ea in ("a","b"):
            for eb in ("a","b"):
                pa,pb=wa[ea],wb[eb];pairs.append((math.hypot(float(pa["x"])-float(pb["x"]),float(pa["y"])-float(pb["y"])),ea,eb))
        _,ea,eb=min(pairs);x=(float(wa[ea]["x"])+float(wb[eb]["x"]))/2;y=(float(wa[ea]["y"])+float(wb[eb]["y"]))/2;wa[ea]=wb[eb]={"x":x,"y":y}
    def _apply(self,s,c,op):
        n=op["tool"];a=op.get("arguments") or {}
        if n=="modify_wall":
            w=self._wall(s,a["wall_id"])
            if a.get("length_mm") is not None:w["lengthCm"]=float(a["length_mm"])/10
            if a.get("thickness_mm") is not None:w["thicknessMm"]=float(a["thickness_mm"])
            if a.get("height_mm") is not None:w["heightMm"]=float(a["height_mm"])
            if a.get("angle_deg") is not None:s.setdefault("ge360AngleOverrides",{})[a["wall_id"]]=float(a["angle_deg"])
        elif n=="delete_wall":
            wid=a["wall_id"];s["walls"]=[x for x in s.get("walls",[]) if str(x.get("id"))!=wid];s["openings"]=[x for x in s.get("openings",[]) if str(x.get("wallId"))!=wid]
            for r in s.get("rooms",[]):r["wallIds"]=[x for x in r.get("wallIds",[]) if str(x)!=wid]
            s["constraints"]=[x for x in s.get("constraints",[]) if wid not in [str(v) for v in (x.get("wallIds") or [])]]
        elif n in {"move_wall","move_vertex"}:
            scale=float((c.plan.get("metadata") or {}).get("scaleMmPerSketchUnit") or 0)
            if scale<=0:raise ValueError("invalid source scale")
            d=float(a["delta_mm"])/scale;dx,dy={"left":(-d,0),"right":(d,0),"up":(0,-d),"down":(0,d)}[a["direction"]]
            if n=="move_wall":
                w=self._wall(s,a["wall_id"])
                for e in ("a","b"):w[e]={"x":float(w[e]["x"])+dx,"y":float(w[e]["y"])+dy}
            else:
                node=next(x for x in c.plan.get("nodes",[]) if str(x.get("id"))==a["node_id"])
                for wid,e in node.get("sourceEndpoints") or []:
                    w=self._wall(s,str(wid));w[str(e)]={"x":float(w[str(e)]["x"])+dx,"y":float(w[str(e)]["y"])+dy}
        elif n=="connect_walls":self._connect(s,a["wall_a"],a["wall_b"])
        elif n=="split_wall":
            w=self._wall(s,a["wall_id"]);total=float(w.get("lengthCm") or 0)*10;d=float(a["distance_from_start_mm"])
            if total<=0 or d>=total:raise ValueError("split outside wall")
            r=d/total;mid={"x":float(w["a"]["x"])+(float(w["b"]["x"])-float(w["a"]["x"]))*r,"y":float(w["a"]["y"])+(float(w["b"]["y"])-float(w["a"]["y"]))*r};second=copy.deepcopy(w);second["id"]=self._id("wall");second["a"]=mid;second["lengthCm"]=(total-d)/10;w["b"]=mid;w["lengthCm"]=d/10;s.setdefault("walls",[]).append(second)
        elif n=="create_wall":
            start=self._node_point(c,s,a["start_node_id"]);scale=float((c.plan.get("metadata") or {}).get("scaleMmPerSketchUnit") or 0)
            if a.get("end_node_id"):end=self._node_point(c,s,a["end_node_id"]);length=math.hypot(end["x"]-start["x"],end["y"]-start["y"])*scale
            else:
                length=float(a["length_mm"]);u=length/scale;dx,dy={"left":(-u,0),"right":(u,0),"up":(0,-u),"down":(0,u)}[a["direction"]];end={"x":start["x"]+dx,"y":start["y"]+dy}
            s.setdefault("walls",[]).append({"id":self._id("wall"),"a":start,"b":end,"lengthCm":length/10,"thicknessMm":a.get("thickness_mm"),"heightMm":a.get("height_mm")})
        elif n in {"create_door","create_window"}:
            width=float(a["width_mm"]);off=a.get("offset_mm")
            if off is None:
                total=float(self._wall(s,a["wall_id"]).get("lengthCm") or 0)*10
                if total<=0:raise ValueError("wall length unavailable")
                off=max(0,(total-width)/2)
            o={"id":self._id("door" if n=="create_door" else "window"),"type":"door" if n=="create_door" else "window","wallId":a["wall_id"],"widthCm":width/10,"offsetCm":float(off)/10,"referenceEnd":a.get("reference_end") or "a"}
            if a.get("height_mm") is not None:o["heightMm"]=float(a["height_mm"])
            if a.get("sill_height_mm") is not None:o["sillHeightMm"]=float(a["sill_height_mm"])
            s.setdefault("openings",[]).append(o)
        elif n=="modify_opening":
            o=self._opening(s,a["opening_id"])
            if a.get("width_mm") is not None:o["widthCm"]=float(a["width_mm"])/10
            if a.get("offset_mm") is not None:o["offsetCm"]=float(a["offset_mm"])/10
            if a.get("offset_delta_mm") is not None:o["offsetCm"]=max(0,float(o.get("offsetCm") or 0)+float(a["offset_delta_mm"])/10)
            if a.get("height_mm") is not None:o["heightMm"]=float(a["height_mm"])
            if a.get("sill_height_mm") is not None:o["sillHeightMm"]=float(a["sill_height_mm"])
        elif n=="delete_opening":s["openings"]=[x for x in s.get("openings",[]) if str(x.get("id"))!=a["opening_id"]]
        elif n=="add_annotation":s.setdefault("notes",[]).append({"id":self._id("note"),"source":"ai-cad-planner",**a})
        elif n=="add_constraint":
            s.setdefault("constraints",[]).append({"id":self._id("constraint"),"kind":a["kind"],"wallIds":a.get("wall_ids",[]),"nodeIds":a.get("node_ids",[]),"source":"user-ai"})
            if a["kind"]=="connect" and len(a.get("wall_ids",[]))>=2:self._connect(s,a["wall_ids"][0],a["wall_ids"][1])
        elif n=="remove_constraint":
            if str(a["constraint_id"]).startswith("solver-"):raise ValueError("cannot remove solver inferred constraint")
            s["constraints"]=[x for x in s.get("constraints",[]) if str(x.get("id"))!=a["constraint_id"]]
        elif n in {"solve_plan","validate_plan","generate_preview"}:return
        else:raise ValueError(f"mutation not implemented: {n}")
    def _evaluate(self,s,out,snap_mul=1,orth_mul=1):
        p=PlanPayload.model_validate(s);snap=min(self.settings.snap_tolerance_mm*snap_mul,self.settings.snap_tolerance_mm*2);orth=min(self.settings.orthogonal_tolerance_deg*orth_mul,45)
        norm=normalize_payload(p,default_thickness_mm=self.settings.default_wall_thickness_mm,default_height_mm=self.settings.default_wall_height_mm,snap_tolerance_mm=snap);top=build_topology(norm);sol=solve_geometry(norm,top,orthogonal_tolerance_deg=orth,length_tolerance_mm=self.settings.length_tolerance_mm)
        ov=source_angle_overrides(s,sol)
        if ov:sol=solve_geometry(norm,top,orthogonal_tolerance_deg=orth,length_tolerance_mm=self.settings.length_tolerance_mm,angle_overrides=ov)
        model=build_cad_model(norm,sol);model.metadata["explicitConstraints"]=s.get("constraints",[]);model.metadata["explicitAngleOverrides"]=s.get("ge360AngleOverrides",{})
        val=validate_geometry(norm,sol,model.rooms,length_tolerance_mm=self.settings.length_tolerance_mm);model.needsReview=bool(model.needsReview or val["needsReview"]);score=geometry_score(val,len(model.rooms));maxgap=float(model.metadata.get("mergedEndpointMaxGapMm",0))
        qs=QualityStatus.NEEDS_REVIEW if model.needsReview else QualityStatus.ESTIMATED if maxgap>10 else QualityStatus.OK;quality={"status":qs.value,"closureErrorCm":val["closureErrorCm"],"maxLengthErrorMm":val["maxLengthErrorMm"],"geometryScore":score,"warnings":val["warnings"],"errors":val["errors"]};model.quality=quality
        self.storage.write_json_atomic(out/"source-plan.json",s);self.storage.write_json_atomic(out/"processed-plan.json",model.model_dump(mode="json"));dx=export_dxf(model,out/"plan.dxf");export_svg(model,out/"plan.svg");export_png(model,out/"preview.png");export_pdf(model,out/"plan.pdf");self.storage.write_json_atomic(out/"plan3d.json",to_plan3d(model));return model,val,quality,dx
    def _diff(self,b,a):
        def d(kind,key):
            x={str(v[key]):v for v in b.get(kind,[]) if key in v};y={str(v[key]):v for v in a.get(kind,[]) if key in v};return {"added":sorted(y.keys()-x.keys()),"deleted":sorted(x.keys()-y.keys())}
        return {"walls":d("walls","id"),"openings":d("openings","id"),"notesChanged":b.get("notes",[])!=a.get("notes",[]),"roomsChanged":b.get("rooms",[])!=a.get("rooms",[])}
    def prepare(self,pid,cmd,instruction=None):
        c=PlanContext(self.storage,pid);s=copy.deepcopy(self._source(pid));s["planId"]=pid;operr=[];applied=[]
        for op in cmd.operations:
            try:self._apply(s,c,op.model_dump(mode="json"));applied.append(op.tool.value)
            except Exception as exc:operr.append({"tool":op.tool.value,"error":str(exc)})
        cid=uuid.uuid4().hex;root=self.storage.ensure(pid)/"candidates"/cid;root.mkdir(parents=True,exist_ok=False);repair=any(o.tool.value in {"solve_plan","validate_plan"} for o in cmd.operations)
        strategies=[("baseline",1,1)]+([("balanced",1.25,1),("repair",1.5,1.15)][:max(0,self.settings.ai_max_strategies-1)] if repair else []);ev=[];serr=[]
        for name,sm,om in strategies:
            v=root/f"strategy-{name}";v.mkdir()
            try:
                model,val,q,dx=self._evaluate(copy.deepcopy(s),v,sm,om);rank=float(q.get("geometryScore") or 0)+(100000 if val.get("valid") else 0);ev.append((rank,name,model,val,q,dx,v))
            except Exception as exc:serr.append({"strategy":name,"error":str(exc)})
        if not ev:raise ValueError("candidate evaluation failed: "+str(serr))
        ev.sort(key=lambda x:x[0],reverse=True);_,chosen,model,val,q,dx,v=ev[0]
        for name in ("source-plan.json","processed-plan.json","plan.dxf","plan.svg","preview.png","plan.pdf","plan3d.json"):shutil.copy2(v/name,root/name)
        status="ready" if val.get("valid") else "invalid";diff=self._diff(c.plan,model.model_dump(mode="json"));meta={"candidateId":cid,"requestId":cmd.request_id,"planId":pid,"baseVersion":c.current_version,"createdAt":datetime.now(timezone.utc).isoformat(),"status":status,"instruction":instruction,"command":cmd.model_dump(mode="json"),"validation":val,"quality":q,"diff":diff,"operationErrors":operr,"appliedOperations":applied,"selectedStrategy":chosen,"strategyErrors":serr,"strategies":[{"name":x[1],"valid":bool(x[3].get("valid")),"geometryScore":x[4].get("geometryScore")} for x in ev]}
        self.storage.write_json_atomic(root/"candidate.json",meta)
        if self.memory:self.memory.mark_candidate(cmd.request_id,status)
        self.audit.append(pid,{"request_id":cmd.request_id,"user_instruction":instruction,"candidate_version":cid,"validation_result":val,"apply_status":"pending","tool_results":{"operation_errors":operr,"selected_strategy":chosen}})
        return CandidatePreview(candidate_id=cid,request_id=cmd.request_id,plan_id=pid,base_version=c.current_version,status=status,validation=val,diff=diff,preview_url=f"/api/v1/plans/{pid}/ai/candidates/{cid}/preview",command=cmd)
    def load_candidate(self,pid,cid):
        if not cid or any(not (x.isalnum() or x in "-_") for x in cid):raise ValueError("invalid candidate id")
        root=self.storage.plan_dir(pid)/"candidates"/cid;p=root/"candidate.json"
        if not p.exists():raise FileNotFoundError("candidate not found")
        return root,json.loads(p.read_text())
    def apply(self,pid,cid,force=False):
        root,m=self.load_candidate(pid,cid)
        if m.get("status")!="ready" and not force:raise ValueError("candidate invalid; force only after explicit confirmation")
        row=self.db.get(pid)
        if not row:raise FileNotFoundError("plan not found")
        if int(row["current_version"])!=int(m["baseVersion"]):raise ValueError("plan changed after preview")
        ver=self.storage.next_version(pid);out=self.storage.version_dir(pid,ver)
        for n in ("source-plan.json","processed-plan.json","plan.dxf","plan.svg","preview.png","plan.pdf","plan3d.json"):shutil.copy2(root/n,out/n)
        model=json.loads((out/"processed-plan.json").read_text());quality=m.get("quality") or {};needs=bool(model.get("needsReview")) or m.get("status")!="ready" or force;status=PlanStatus.NEEDS_REVIEW if needs else PlanStatus.PROCESSED
        summary={"rooms":len(model.get("rooms",[])),"floorAreaM2":round(sum(float(r.get("floorAreaM2") or 0) for r in model.get("rooms",[])),6)}
        man={"planId":pid,"version":ver,"status":status.value,"createdAt":datetime.now(timezone.utc).isoformat(),"completedAt":datetime.now(timezone.utc).isoformat(),"quality":quality,"summary":summary,"files":[],"ai":{"authoritative":False,"requestId":m.get("requestId"),"candidateId":cid,"forced":force}}
        self.storage.write_json_atomic(out/"manifest.json",man);man["files"]=sorted(p.name for p in out.iterdir() if p.is_file() and p.name!="manifest.json");self.storage.write_json_atomic(out/"manifest.json",man);self.storage.publish_current(pid,out);self.db.set_status(pid,status,version=ver,quality=quality,needs_review=needs,error="")
        m.update(applyStatus="forced_applied" if force else "applied",appliedVersion=ver,forced=bool(force));self.storage.write_json_atomic(root/"candidate.json",m)
        if self.memory:self.memory.mark_applied(str(m.get("requestId") or ""),forced=force)
        self.audit.append(pid,{"request_id":m.get("requestId"),"candidate_version":cid,"validation_result":m.get("validation"),"apply_status":m["applyStatus"],"authoritative_version":ver})
        return {"success":True,"planId":pid,"candidateId":cid,"version":ver,"status":status.value,"forced":bool(force)}
    def restore_version(self,pid,direction,steps=1):
        row=self.db.get(pid)
        if not row:raise FileNotFoundError("plan not found")
        cur=int(row["current_version"]);root=self.storage.plan_dir(pid)/"versions";available=[]
        for p in root.iterdir() if root.exists() else []:
            if p.is_dir() and p.name.isdigit() and (p/"manifest.json").exists() and (p/"source-plan.json").exists() and (p/"processed-plan.json").exists():
                try:
                    m=json.loads((p/"manifest.json").read_text())
                    if m.get("status") in {PlanStatus.PROCESSED.value,PlanStatus.NEEDS_REVIEW.value}:available.append(int(p.name))
                except Exception:pass
        target=cur
        for _ in range(max(1,steps)):
            xs=[v for v in available if v<target] if direction<0 else [v for v in available if v>target]
            if not xs:break
            target=max(xs) if direction<0 else min(xs)
        if target==cur:raise ValueError("no version in requested direction")
        src=root/f"{target:03d}";self.storage.publish_current(pid,src);m=json.loads((src/"manifest.json").read_text());quality=m.get("quality") or {};status=PlanStatus(m.get("status"));self.db.set_status(pid,status,version=target,quality=quality,needs_review=status==PlanStatus.NEEDS_REVIEW,error="")
        return {"success":True,"planId":pid,"version":target,"status":status.value}
