from __future__ import annotations

import json
import logging
import secrets
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.notes import rewrite_note
from backend.agent.ollama import OllamaClient
from backend.bridge import BridgeSettings, BridgeUnavailable, DirectBridgeManager
from backend.bridge.schemas import CreateBridgeDeviceRequest

from backend.config import get_settings
from backend.connectivity import connection_profile, generate_runtime_api_key, read_runtime_api_key
from backend.db import Database
from backend.jobs import JobManager
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage

logger = logging.getLogger("ge360.rilievi")
settings = get_settings()
_runtime_api_key = read_runtime_api_key(settings)
if settings.require_api_key and not _runtime_api_key:
    raise RuntimeError(
        "GE360 SECURITY: API key required. Set GE360_API_KEY or GE360_API_KEY_FILE before starting."
    )
storage = PlanStorage(settings.data_dir)
db = Database(settings.db_path)
pipeline = Pipeline(settings, storage, db)
jobs = JobManager(pipeline, max_workers=settings.job_workers)
_bridge_manager: DirectBridgeManager | None = None

if not _runtime_api_key:
    logger.warning("GE360 API key disabled explicitly for development")
if "*" in settings.cors_origins:
    logger.warning("GE360_CORS_ORIGINS contains '*'; use explicit origins in production")

app = FastAPI(title="GE360 Rilievi Backend", version="1.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-GE360-API-Key"],
)

viewer_dir = Path(__file__).resolve().parents[1] / "viewer3d"
if viewer_dir.is_dir():
    app.mount("/viewer3d", StaticFiles(directory=viewer_dir, html=True), name="viewer3d")

setup_dir = Path(__file__).resolve().parents[1] / "setup"
if setup_dir.is_dir():
    app.mount("/setup", StaticFiles(directory=setup_dir, html=True), name="setup")

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
    api_key = read_runtime_api_key(settings)
    if not api_key:
        if settings.require_api_key:
            raise HTTPException(status_code=503, detail="GE360 API key is not configured")
        return
    if x_ge360_api_key and secrets.compare_digest(x_ge360_api_key, api_key):
        return
    if x_ge360_api_key and x_ge360_api_key.startswith("ge360d_"):
        try:
            if get_bridge_manager().authenticate_app_token(x_ge360_api_key):
                return
        except HTTPException:
            pass
    raise HTTPException(status_code=401, detail="Invalid API key")


def _direct_local_setup_request(request: Request) -> bool:
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return False
    request_host = (request.url.hostname or "").lower()
    client_host = (request.client.host if request.client else "").lower()
    loopback = {"127.0.0.1", "::1", "localhost"}
    return request_host in loopback and client_host in loopback


def require_setup_access(
    request: Request,
    x_ge360_api_key: str | None = Header(default=None),
) -> None:
    if _direct_local_setup_request(request):
        return
    api_key = read_runtime_api_key(settings)
    if api_key and x_ge360_api_key and secrets.compare_digest(x_ge360_api_key, api_key):
        return
    raise HTTPException(
        status_code=403,
        detail="Setup is available directly from localhost or with a valid GE360 API key",
    )


def get_bridge_manager() -> DirectBridgeManager:
    global _bridge_manager
    if _bridge_manager is not None:
        return _bridge_manager
    try:
        _bridge_manager = DirectBridgeManager(BridgeSettings.from_env(settings.port))
        return _bridge_manager
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "BRIDGE_STORAGE_UNAVAILABLE", "message": str(exc)},
        ) from exc


def _bridge_call(action):
    try:
        return action()
    except BridgeUnavailable as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "BRIDGE_OPERATION_FAILED", "message": str(exc)},
        ) from exc


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
        "version": "1.4.0",
        "aiEnabled": settings.ai_enabled,
        "apiKeyRequired": bool(read_runtime_api_key(settings)) or settings.require_api_key,
        "setupUrl": "/setup/",
    }


@app.get("/api/v1/setup/status", dependencies=[Depends(require_setup_access)])
def setup_status():
    return connection_profile(settings)


@app.post("/api/v1/setup/api-key", dependencies=[Depends(require_setup_access)])
def setup_generate_api_key():
    key = generate_runtime_api_key(settings)
    profile = connection_profile(settings)
    return {
        "ok": True,
        "apiKey": key,
        "shownOnce": True,
        "frontendServerUrl": profile["tailscale"]["frontendServerUrl"]
        or profile["local"]["frontendServerUrl"],
        "profile": profile,
    }


@app.get("/api/v1/bridge/status", dependencies=[Depends(require_setup_access)])
def bridge_status():
    return _bridge_call(lambda: get_bridge_manager().status())


@app.post("/api/v1/bridge/devices", dependencies=[Depends(require_setup_access)])
def bridge_create_device(payload: CreateBridgeDeviceRequest):
    return _bridge_call(lambda: get_bridge_manager().create_device(payload.name))


@app.get("/api/v1/bridge/devices", dependencies=[Depends(require_setup_access)])
def bridge_devices():
    return _bridge_call(lambda: get_bridge_manager().list_devices())


@app.get("/api/v1/bridge/devices/{device_id}", dependencies=[Depends(require_setup_access)])
def bridge_device(device_id: str):
    device = _bridge_call(lambda: get_bridge_manager().get_device(device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Bridge device not found")
    return device


@app.delete("/api/v1/bridge/devices/{device_id}", dependencies=[Depends(require_setup_access)])
@app.post("/api/v1/bridge/devices/{device_id}/revoke", dependencies=[Depends(require_setup_access)])
def bridge_revoke_device(device_id: str):
    device = _bridge_call(lambda: get_bridge_manager().revoke_device(device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Bridge device not found")
    return {"ok": True, "device": device}


@app.get("/api/v1/bridge/devices/{device_id}/qr", dependencies=[Depends(require_setup_access)])
def bridge_pairing_qr_not_persisted(device_id: str):
    device = _bridge_call(lambda: get_bridge_manager().get_device(device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Bridge device not found")
    raise HTTPException(
        status_code=410,
        detail={
            "code": "PAIRING_QR_SHOWN_ONCE",
            "message": "Il QR contiene la private key WireGuard e la chiave applicativa del dispositivo; è disponibile solo nella risposta di creazione.",
        },
    )


@app.post("/api/v1/bridge/restart", dependencies=[Depends(require_setup_access)])
def bridge_restart():
    return _bridge_call(lambda: get_bridge_manager().restart())


@app.get("/api/v1/bridge/diagnostics", dependencies=[Depends(require_setup_access)])
def bridge_diagnostics():
    return _bridge_call(lambda: get_bridge_manager().diagnostics())


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




_ALLOWED_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_MAX_PHOTO_BYTES = 12 * 1024 * 1024


def _public_media(row: dict) -> dict:
    return {
        "id": row["media_id"],
        "planId": row["plan_id"],
        "targetType": row["target_type"],
        "targetId": row.get("target_id"),
        "caption": row.get("caption"),
        "mimeType": row["mime_type"],
        "filename": row["filename"],
        "sizeBytes": row["size_bytes"],
        "createdAt": row["created_at"],
        "url": f"/api/v1/plans/{row['plan_id']}/photos/{row['media_id']}",
    }


@app.post("/api/v1/plans/{plan_id}/photos", dependencies=[Depends(require_api_key)])
async def upload_plan_photo(
    plan_id: str,
    file: UploadFile = File(...),
    targetType: str = Form("plan"),
    targetId: str | None = Form(default=None),
    caption: str | None = Form(default=None),
):
    _record_or_404(plan_id)
    mime = (file.content_type or "").lower()
    suffix = _ALLOWED_IMAGE_MIME.get(mime)
    if suffix is None:
        raise HTTPException(status_code=415, detail="Supported photos: JPEG, PNG, WEBP")
    data = await file.read(_MAX_PHOTO_BYTES + 1)
    if len(data) > _MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo too large (max 12 MB)")
    if not data:
        raise HTTPException(status_code=422, detail="Empty photo")
    if targetType not in {"plan", "wall", "room", "opening"}:
        raise HTTPException(status_code=422, detail="Invalid photo targetType")
    media_id = uuid.uuid4().hex
    path = storage.media_path(plan_id, media_id, suffix)
    storage.write_bytes_atomic(path, data)
    row = db.add_media(
        media_id=media_id,
        plan_id=plan_id,
        target_type=targetType,
        target_id=targetId,
        caption=(caption or "").strip()[:500] or None,
        mime_type=mime,
        filename=(file.filename or f"{media_id}{suffix}")[:200],
        path=str(path),
        size_bytes=len(data),
    )
    return {"ok": True, "photo": _public_media(row)}


@app.get("/api/v1/plans/{plan_id}/photos", dependencies=[Depends(require_api_key)])
def list_plan_photos(plan_id: str):
    _record_or_404(plan_id)
    return {"planId": plan_id, "photos": [_public_media(row) for row in db.list_media(plan_id)]}


@app.get("/api/v1/plans/{plan_id}/photos/{media_id}", dependencies=[Depends(require_api_key)])
def get_plan_photo(plan_id: str, media_id: str):
    _record_or_404(plan_id)
    row = db.get_media(media_id)
    if not row or row["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = Path(row["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Photo file missing")
    return FileResponse(path, media_type=row["mime_type"], filename=row["filename"])


@app.delete("/api/v1/plans/{plan_id}/photos/{media_id}", dependencies=[Depends(require_api_key)])
def delete_plan_photo(plan_id: str, media_id: str):
    _record_or_404(plan_id)
    row = db.get_media(media_id)
    if not row or row["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    removed = db.delete_media(media_id)
    if removed:
        try:
            Path(removed["path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


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
        "totals": current_manifest.get("totals"),
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
