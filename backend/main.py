from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.ollama import OllamaClient
from backend.agent.notes import rewrite_note
from backend.config import get_settings
from backend.db import Database
from backend.jobs import JobManager
from backend.models import PlanPayload, PlanStatus
from backend.pipeline import Pipeline
from backend.storage import PlanStorage


settings = get_settings()
storage = PlanStorage(settings.data_dir)
db = Database(settings.db_path)
pipeline = Pipeline(settings, storage, db)
jobs = JobManager(pipeline)

app = FastAPI(title="GE360 Rilievi Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "https://localhost", "capacitor://localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-GE360-API-Key"],
)


def require_api_key(x_ge360_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="GE360_API_KEY not configured")
    if not x_ge360_api_key or not secrets.compare_digest(x_ge360_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _record_or_404(plan_id: str):
    row = db.get(plan_id)
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    return row


def _current_file(plan_id: str, filename: str) -> Path:
    _record_or_404(plan_id)
    path = storage.plan_dir(plan_id) / "current" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not available")
    return path


@app.get("/healthz")
def healthz():
    return {"ok":True,"service":"ge360-rilievi-backend"}


@app.get("/api/v1/health", dependencies=[Depends(require_api_key)])
def health():
    return {"ok":True,"service":"ge360-rilievi-backend","version":"1.0.0","aiEnabled":settings.ai_enabled}


class NoteRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    rawText: str
    planId: str | None = None
    planName: str | None = None
    targetType: str
    targetId: str | None = None
    targetLabel: str | None = None
    roomName: str | None = None
    context: dict = Field(default_factory=dict)


@app.post("/api/v1/notes/rewrite", dependencies=[Depends(require_api_key)])
def notes_rewrite(payload: NoteRewriteRequest):
    raw = payload.rawText.strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Appunto vuoto")
    if len(raw) > 5000:
        raise HTTPException(status_code=422, detail="Appunto troppo lungo")
    client = OllamaClient(settings.ollama_url, settings.ollama_model, settings.ollama_timeout)
    result = rewrite_note(client, payload.model_dump(mode="json"))
    if result is None:
        raise HTTPException(status_code=503, detail="Ollama non raggiungibile")
    return {
        "ok": True,
        "model": settings.ollama_model,
        "rawText": raw,
        "cleanedText": str(result.get("cleanedText") or raw),
        "tasks": [str(x) for x in (result.get("tasks") or [])],
        "needsClarification": [str(x) for x in (result.get("needsClarification") or [])],
    }


@app.post("/api/v1/plans", dependencies=[Depends(require_api_key)])
def create_plan(payload: PlanPayload):
    return pipeline.save_raw(payload)


@app.post("/api/v1/plans/refine", dependencies=[Depends(require_api_key)])
def frontend_refine(payload: PlanPayload):
    pipeline.save_raw(payload)
    job_id = jobs.submit(payload.planId)
    return {"ok":True,"success":True,"planId":payload.planId,"jobId":job_id,"status":PlanStatus.PROCESSING.value}


@app.post("/api/v1/plans/{plan_id}/process", dependencies=[Depends(require_api_key)])
def process_plan(plan_id: str):
    _record_or_404(plan_id)
    job_id=jobs.submit(plan_id)
    return {"success":True,"planId":plan_id,"jobId":job_id,"status":PlanStatus.PROCESSING.value}


@app.post("/api/v1/plans/{plan_id}/reprocess", dependencies=[Depends(require_api_key)])
def reprocess_plan(plan_id: str):
    return process_plan(plan_id)


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def job_status(job_id: str):
    result=jobs.state(job_id)
    if result is None:
        raise HTTPException(status_code=404,detail="Job not found")
    return result


@app.get("/api/v1/plans/{plan_id}", dependencies=[Depends(require_api_key)])
def plan_status(plan_id: str):
    row=_record_or_404(plan_id)
    return {
        "planId":row["plan_id"],"name":row["name"],"status":row["status"],
        "currentVersion":row["current_version"],"quality":row["quality"],
        "needsReview":row["needsReview"],"updatedAt":row["updated_at"],"lastError":row["last_error"],
    }


@app.get("/api/v1/plans/{plan_id}/processed", dependencies=[Depends(require_api_key)])
def processed(plan_id: str):
    return FileResponse(_current_file(plan_id,"processed-plan.json"),media_type="application/json")


@app.get("/api/v1/plans/{plan_id}/preview", dependencies=[Depends(require_api_key)])
def preview(plan_id: str):
    return FileResponse(_current_file(plan_id,"preview.png"),media_type="image/png")


@app.get("/api/v1/plans/{plan_id}/svg", dependencies=[Depends(require_api_key)])
def svg(plan_id: str):
    return FileResponse(_current_file(plan_id,"plan.svg"),media_type="image/svg+xml")


@app.get("/api/v1/plans/{plan_id}/dxf", dependencies=[Depends(require_api_key)])
def dxf(plan_id: str):
    return FileResponse(_current_file(plan_id,"plan.dxf"),media_type="application/dxf",filename=f"{plan_id}.dxf")


@app.get("/api/v1/plans/{plan_id}/pdf", dependencies=[Depends(require_api_key)])
def pdf(plan_id: str):
    return FileResponse(_current_file(plan_id,"plan.pdf"),media_type="application/pdf",filename=f"{plan_id}.pdf")


@app.get("/api/v1/plans/{plan_id}/3d", dependencies=[Depends(require_api_key)])
def plan3d(plan_id: str):
    return FileResponse(_current_file(plan_id,"plan3d.json"),media_type="application/json")


@app.get("/api/v1/plans/{plan_id}/glb", dependencies=[Depends(require_api_key)])
def glb(plan_id: str):
    return FileResponse(_current_file(plan_id,"plan.glb"),media_type="model/gltf-binary",filename=f"{plan_id}.glb")


@app.get("/api/v1/plans/{plan_id}/versions", dependencies=[Depends(require_api_key)])
def versions(plan_id: str):
    _record_or_404(plan_id)
    root=storage.plan_dir(plan_id)/"versions"
    rows=[]
    for p in sorted(root.iterdir()) if root.exists() else []:
        if p.is_dir() and p.name.isdigit():
            rows.append({"version":int(p.name),"files":sorted(x.name for x in p.iterdir() if x.is_file())})
    return {"planId":plan_id,"versions":rows}
