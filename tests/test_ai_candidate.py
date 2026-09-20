from __future__ import annotations
import json
from pathlib import Path
from backend.ai.audit import AIAuditLog
from backend.ai.candidate import CandidateService
from backend.ai.schemas import CADCommandBatch,CADOperation
from backend.config import Settings
from backend.db import Database
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage

def wall(i,a,b,cm):return {"id":i,"a":{"x":a[0],"y":a[1]},"b":{"x":b[0],"y":b[1]},"lengthCm":cm}
def settings(tmp):
    return Settings("",tmp/"data",tmp/"data/db.sqlite3","127.0.0.1",9888,120,2700,250,25,.5,False,"http://127.0.0.1:11434","qwen3:8b",.1)
def payload():
    return PlanPayload.model_validate({"version":4,"planId":"candidate","name":"Candidate","walls":[wall("wall_001",(0,0),(400,0),400),wall("wall_002",(400,0),(400,300),300),wall("wall_003",(400,300),(0,300),400),wall("wall_004",(0,300),(0,0),300)]})

def test_candidate_preview_apply_reprocess_preserves_source(tmp_path:Path):
    s=settings(tmp_path);storage=PlanStorage(s.data_dir);db=Database(s.db_path);pipe=Pipeline(s,storage,db)
    pipe.save_raw(payload());first=pipe.process("candidate");assert first["version"]==1
    raw=(storage.plan_dir("candidate")/"raw/original.json").read_bytes()
    service=CandidateService(s,storage,db,AIAuditLog(storage))
    cmd=CADCommandBatch(request_id="req-1",prompt_version="cad-planner-v2-best-effort",operations=[CADOperation(tool="modify_wall",arguments={"wall_id":"wall_001","length_mm":4200})])
    preview=service.prepare("candidate",cmd,"allunga questo muro a 4,20 metri")
    assert preview.status in {"ready","invalid"} and "wall_001" in preview.diff["walls"]["modified"]
    assert db.get("candidate")["current_version"]==1
    applied=service.apply("candidate",preview.candidate_id,force=preview.status=="invalid");assert applied["version"]==2
    source=json.loads((storage.plan_dir("candidate")/"current/source-plan.json").read_text())
    assert next(w for w in source["walls"] if w["id"]=="wall_001")["lengthCm"]==420.0
    assert (storage.plan_dir("candidate")/"raw/original.json").read_bytes()==raw
    third=pipe.process("candidate");assert third["version"]==3
    current=json.loads((storage.plan_dir("candidate")/"current/processed-plan.json").read_text())
    assert next(w for w in current["walls"] if w["id"]=="wall_001")["declaredLengthMm"]==4200
    assert (storage.plan_dir("candidate")/"raw/original.json").read_bytes()==raw

def test_annotation_candidate_does_not_touch_raw(tmp_path:Path):
    s=settings(tmp_path);storage=PlanStorage(s.data_dir);db=Database(s.db_path);pipe=Pipeline(s,storage,db)
    pipe.save_raw(payload());pipe.process("candidate");raw=(storage.plan_dir("candidate")/"raw/original.json").read_bytes()
    service=CandidateService(s,storage,db,AIAuditLog(storage))
    cmd=CADCommandBatch(request_id="req-note",prompt_version="cad-planner-v2-best-effort",requires_solver=False,operations=[CADOperation(tool="add_annotation",arguments={"target_type":"wall","target_id":"wall_001","category":"demolition","text":"Parete da demolire"})])
    preview=service.prepare("candidate",cmd);assert preview.diff["notesChanged"] is True
    service.apply("candidate",preview.candidate_id,force=preview.status=="invalid")
    assert (storage.plan_dir("candidate")/"raw/original.json").read_bytes()==raw
