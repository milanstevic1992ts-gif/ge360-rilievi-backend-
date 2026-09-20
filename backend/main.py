from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.notes import rewrite_note
from backend.agent.ollama import OllamaClient

from backend.config import get_settings
from backend.db import Database
from backend.jobs import JobManager
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage

logger = logging.getLogger("ge360.rilievi")
settings = get_settings()
storage = PlanStorage(settings.data_dir)
db = Database(settings.db_path)
pipeline = Pipeline(settings, storage, db)
jobs = JobManager(pipeline, max_workers=settings.job_workers)

if not settings.api_key:
    logger.warning("GE360_API_KEY is empty: local/development API is running without authentication")
if "*" in settings.cors_origins:
    logger.warning("GE360_CORS_ORIGINS contains '*'; use explicit origins in production")

app = FastAPI(title="GE360 Rilievi Backend", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-GE360-API-Key"],
)

viewer_dir = Path(__file__).resolve().parents[1] / "viewer3d"
if viewer_dir.is_dir():
    app.mount("/viewer3d", StaticFiles(directory=viewer_dir, html=True), name="viewer3d")

ARTIFACTS: dict[str, tuple[str, str, bool]] = {
    "processed": ("processed-plan.json", "application/json", False),
    "preview": ("preview.png", "image/png", False),
    "png": ("preview.png", "image/png", False),
    "svg": ("plan.svg", "image/svg+xml", False),
    "pdf": ("plan.pdf", "application/pdf", True),
    "dxf": ("plan.dxf", "application/dxf", True),
    "3d": ("plan3d.json", "application/json", False),
}


def require_api_key(x_ge360_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        return
    if not x_ge360_api_key or not secrets.compare_digest(x_ge360_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _record_or_404(plan_id: str) -> dict:
    row = db.get(plan_id)
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")
    return row


def _manifest(path: Path) -> dict | None:
    manifest = path / "manifest.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _artifact_response(plan_id: str, base: Path, artifact: str, version: int | None = None):
    _record_or_404(plan_id)
    if artifact not in ARTIFACTS:
        raise HTTPException(status_code=404, detail="Unknown artifact")
    filename, media_type, attachment = ARTIFACTS[artifact]
    path = base / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not available")
    download_name = None
    if attachment:
        suffix = path.suffix
        download_name = f"{plan_id}-v{version:03d}{suffix}" if version else f"{plan_id}{suffix}"
    return FileResponse(path, media_type=media_type, filename=download_name)


def _current_file_links(plan_id: str) -> dict[str, str | None]:
    current = storage.plan_dir(plan_id) / "current"

    def link(artifact: str) -> str | None:
        filename = ARTIFACTS[artifact][0]
        return f"/api/v1/plans/{plan_id}/{artifact}" if (current / filename).exists() else None

    return {
        "preview": link("preview"),
        "png": link("png"),
        "svg": link("svg"),
        "pdf": link("pdf"),
        "dxf": link("dxf"),
        "json": link("processed"),
        "plan3d": link("3d"),
        "viewer": f"/viewer3d/?plan=/api/v1/plans/{plan_id}/3d" if (current / "plan3d.json").exists() else None,
        "glb": None,
    }


def _queue_plan(plan_id: str) -> dict:
    row = _record_or_404(plan_id)
    submission = jobs.submit(plan_id)
    job_id = submission["jobId"]
    return {
        "success": True,
        "planId": plan_id,
        "jobId": job_id,
        "status": submission["status"],
        "queued": submission["created"],
        "currentVersion": row["current_version"],
        "statusUrl": f"/api/v1/plans/{plan_id}",
        "jobUrl": f"/api/v1/jobs/{job_id}" if job_id else None,
        "versionsUrl": f"/api/v1/plans/{plan_id}/versions",
        "viewerUrl": f"/viewer3d/?plan=/api/v1/plans/{plan_id}/3d",
    }


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "ge360-rilievi-backend"}


@app.get("/api/v1/health", dependencies=[Depends(require_api_key)])
def health():
    return {
        "ok": True,
        "service": "ge360-rilievi-backend",
        "version": "1.2.0",
        "aiEnabled": settings.ai_enabled,
        "apiKeyRequired": bool(settings.api_key),
    }


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
    result = rewrite_note(
        OllamaClient(settings.ollama_url, settings.ollama_model, settings.ollama_timeout),
        payload.model_dump(mode="json"),
    )
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
    saved = pipeline.save_raw(payload)
    queued = _queue_plan(saved["planId"])
    return {"ok": True, **queued}


@app.post("/api/v1/plans/{plan_id}/process", dependencies=[Depends(require_api_key)])
def process_plan(plan_id: str):
    return _queue_plan(plan_id)


@app.post("/api/v1/plans/{plan_id}/reprocess", dependencies=[Depends(require_api_key)])
def reprocess_plan(plan_id: str):
    return _queue_plan(plan_id)


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def job_status(job_id: str):
    result = jobs.state(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.get("/api/v1/plans/{plan_id}", dependencies=[Depends(require_api_key)])
def plan_status(plan_id: str):
    row = _record_or_404(plan_id)
    current_manifest = _manifest(storage.plan_dir(plan_id) / "current") or {}
    summary = current_manifest.get("summary") or {"rooms": 0, "floorAreaM2": 0.0}
    return {
        "success": True,
        "planId": row["plan_id"],
        "name": row["name"],
        "status": row["status"],
        "currentVersion": row["current_version"],
        "needsReview": row["needsReview"],
        "quality": row["quality"],
        "summary": summary,
        "files": _current_file_links(plan_id),
        "updatedAt": row["updated_at"],
        "lastError": row["last_error"],
    }


@app.get("/api/v1/plans/{plan_id}/processed", dependencies=[Depends(require_api_key)])
def processed(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "processed")


@app.get("/api/v1/plans/{plan_id}/preview", dependencies=[Depends(require_api_key)])
def preview(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "preview")


@app.get("/api/v1/plans/{plan_id}/png", dependencies=[Depends(require_api_key)])
def png(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "png")


@app.get("/api/v1/plans/{plan_id}/svg", dependencies=[Depends(require_api_key)])
def svg(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "svg")


@app.get("/api/v1/plans/{plan_id}/dxf", dependencies=[Depends(require_api_key)])
def dxf(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "dxf")


@app.get("/api/v1/plans/{plan_id}/pdf", dependencies=[Depends(require_api_key)])
def pdf(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "pdf")


@app.get("/api/v1/plans/{plan_id}/3d", dependencies=[Depends(require_api_key)])
def plan3d(plan_id: str):
    return _artifact_response(plan_id, storage.plan_dir(plan_id) / "current", "3d")


@app.get("/api/v1/plans/{plan_id}/glb", dependencies=[Depends(require_api_key)])
def glb_unavailable(plan_id: str):
    _record_or_404(plan_id)
    raise HTTPException(status_code=404, detail="GLB is not generated in V1")


@app.get("/api/v1/plans/{plan_id}/versions", dependencies=[Depends(require_api_key)])
def versions(plan_id: str):
    _record_or_404(plan_id)
    root = storage.plan_dir(plan_id) / "versions"
    rows = []
    for path in sorted(root.iterdir(), reverse=True) if root.exists() else []:
        if not path.is_dir() or not path.name.isdigit():
            continue
        manifest = _manifest(path) or {}
        quality = manifest.get("quality") or {}
        rows.append(
            {
                "version": int(path.name),
                "status": manifest.get("status", "UNKNOWN"),
                "createdAt": manifest.get("createdAt"),
                "completedAt": manifest.get("completedAt"),
                "quality": quality.get("status"),
                "qualityDetail": quality or None,
                "summary": manifest.get("summary"),
                "files": manifest.get("files", []),
            }
        )
    return rows


@app.get("/api/v1/plans/{plan_id}/versions/{version}", dependencies=[Depends(require_api_key)])
def version_metadata(plan_id: str, version: int):
    _record_or_404(plan_id)
    path = storage.plan_dir(plan_id) / "versions" / f"{version:03d}"
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Version not found")
    manifest = _manifest(path)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Version manifest not available")
    return manifest


@app.get(
    "/api/v1/plans/{plan_id}/versions/{version}/{artifact}",
    dependencies=[Depends(require_api_key)],
)
def version_artifact(plan_id: str, version: int, artifact: str):
    _record_or_404(plan_id)
    path = storage.plan_dir(plan_id) / "versions" / f"{version:03d}"
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Version not found")
    return _artifact_response(plan_id, path, artifact, version=version)
