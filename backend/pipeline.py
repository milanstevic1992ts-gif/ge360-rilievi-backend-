from __future__ import annotations
import copy,time,traceback,uuid
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

class Pipeline:
    def __init__(self,settings,storage,db):self.settings=settings;self.storage=storage;self.db=db
    def save_raw(self,payload):
        if not payload.planId:payload=payload.model_copy(update={"planId":uuid.uuid4().hex})
        data=payload.model_dump(mode="json");p=self.storage.save_raw(payload.planId,data);self.db.upsert_raw(payload.planId,payload.name,self.storage.plan_dir(payload.planId));self.storage.append_log(payload.planId,{"event":"raw_saved","inputHash":self.storage.sha256_json(data),"path":str(p)});return {"success":True,"planId":payload.planId,"status":PlanStatus.RAW.value}
    def process(self,pid):
        started=time.perf_counter();created=datetime.now(timezone.utc).isoformat();source,kind=self.storage.authoritative_payload(pid);source=copy.deepcopy(source);source.setdefault("planId",pid);h=self.storage.sha256_json(source);self.db.set_status(pid,PlanStatus.PROCESSING,error="");ver=self.storage.next_version(pid);out=self.storage.version_dir(pid,ver);initial={"planId":pid,"version":ver,"status":PlanStatus.PROCESSING.value,"createdAt":created,"inputHash":h,"inputSource":kind,"files":[],"glb":None};self.storage.write_json_atomic(out/"manifest.json",initial)
        try:
            p=PlanPayload.model_validate(source);norm=normalize_payload(p,default_thickness_mm=self.settings.default_wall_thickness_mm,default_height_mm=self.settings.default_wall_height_mm,snap_tolerance_mm=self.settings.snap_tolerance_mm);top=build_topology(norm);sol=solve_geometry(norm,top,orthogonal_tolerance_deg=self.settings.orthogonal_tolerance_deg,length_tolerance_mm=self.settings.length_tolerance_mm);ov=source_angle_overrides(source,sol)
            if ov:sol=solve_geometry(norm,top,orthogonal_tolerance_deg=self.settings.orthogonal_tolerance_deg,length_tolerance_mm=self.settings.length_tolerance_mm,angle_overrides=ov)
            model=build_cad_model(norm,sol);model.metadata["explicitConstraints"]=source.get("constraints",[]);model.metadata["explicitAngleOverrides"]=source.get("ge360AngleOverrides",{});val=validate_geometry(norm,sol,model.rooms,length_tolerance_mm=self.settings.length_tolerance_mm);model.needsReview=bool(model.needsReview or val["needsReview"]);score=geometry_score(val,len(model.rooms));maxgap=float(model.metadata.get("mergedEndpointMaxGapMm",0));qs=QualityStatus.NEEDS_REVIEW if model.needsReview else QualityStatus.ESTIMATED if maxgap>10 else QualityStatus.OK;quality={"status":qs.value,"closureErrorCm":val["closureErrorCm"],"maxLengthErrorMm":val["maxLengthErrorMm"],"geometryScore":score,"warnings":val["warnings"],"errors":val["errors"]};model.quality=quality
            self.storage.write_json_atomic(out/"source-plan.json",source);self.storage.write_json_atomic(out/"processed-plan.json",model.model_dump(mode="json"));dx=export_dxf(model,out/"plan.dxf");export_svg(model,out/"plan.svg");export_png(model,out/"preview.png");export_pdf(model,out/"plan.pdf");self.storage.write_json_atomic(out/"plan3d.json",to_plan3d(model))
            status=PlanStatus.NEEDS_REVIEW if model.needsReview else PlanStatus.PROCESSED;summary={"rooms":len(model.rooms),"floorAreaM2":round(sum(x.floorAreaM2 for x in model.rooms),6)};man={"planId":pid,"version":ver,"status":status.value,"createdAt":created,"completedAt":datetime.now(timezone.utc).isoformat(),"inputHash":h,"inputSource":kind,"quality":quality,"summary":summary,"dxfValidation":dx,"files":[],"glb":None,"agent":{"enabled":self.settings.ai_enabled,"mode":"copilot-only","authoritative":False,"invoked":False,"offline":True,"aiAvailable":False,"iterations":0,"proposals":[],"accepted":[],"rejected":[]}};self.storage.write_json_atomic(out/"manifest.json",man);man["files"]=sorted(x.name for x in out.iterdir() if x.is_file() and x.name!="manifest.json");self.storage.write_json_atomic(out/"manifest.json",man);self.storage.publish_current(pid,out);self.db.set_status(pid,status,version=ver,quality=quality,needs_review=model.needsReview,error="")
            if kind=="raw":self.storage.mark_raw_consumed(pid)
            self.storage.append_log(pid,{"event":"processing_completed","inputSource":kind,"version":ver,"aiInvoked":False,"geometryScoreAfter":score,"processingTimeMs":round((time.perf_counter()-started)*1000,2)})
            return {"success":True,"planId":pid,"status":status.value,"version":ver,"needsReview":model.needsReview,"quality":quality,"summary":summary,"aiAvailable":False,"aiMode":"copilot-only","files":{"processed":"processed-plan.json","preview":"preview.png","png":"preview.png","svg":"plan.svg","pdf":"plan.pdf","dxf":"plan.dxf","3d":"plan3d.json","glb":None},"geometry":{"walls":[w.model_dump(mode="json") for w in model.walls],"openings":[o.model_dump(mode="json") for o in model.openings],"rooms":[r.model_dump(mode="json") for r in model.rooms]}}
        except Exception as exc:
            self.storage.write_json_atomic(out/"manifest.json",{**initial,"status":PlanStatus.ERROR.value,"completedAt":datetime.now(timezone.utc).isoformat(),"error":str(exc)});self.db.set_status(pid,PlanStatus.ERROR,error=str(exc));self.storage.append_log(pid,{"event":"processing_error","version":ver,"error":str(exc),"traceback":traceback.format_exc(limit=12)});raise
