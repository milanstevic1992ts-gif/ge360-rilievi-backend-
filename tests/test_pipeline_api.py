from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import Database
from backend.jobs import JobManager
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage


def wall(i, a, b, cm):
    return {"id": i, "a": {"x": a[0], "y": a[1]}, "b": {"x": b[0], "y": b[1]}, "lengthCm": cm}


def payload(plan_id="e2e"):
    p = {"version": 4, "name": "Camera 2x3", "wallHeightM": 2.7, "walls": [
        wall("w1", (0, 0), (202, 8), 200), wall("w2", (202, 8), (211, 306), 300),
        wall("w3", (211, 306), (5, 299), 200), wall("w4", (5, 299), (0, 0), 300),
    ]}
    if plan_id is not None:
        p["planId"] = plan_id
    return p


def cfg(tmp: Path):
    return Settings("test-key", tmp/"data", tmp/"data/db.sqlite3", "127.0.0.1", 9888,
                    120, 2700, 250, 25, .5, False, "http://127.0.0.1:11434", "qwen2.5:7b", .1)


def wait_job(client, job_id, headers):
    for _ in range(250):
        state = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if state["status"] in {"DONE", "ERROR"}:
            return state
        time.sleep(.02)
    raise AssertionError("job timeout")


def test_pipeline_versions_and_immutable_raw(tmp_path: Path):
    s = cfg(tmp_path); storage = PlanStorage(s.data_dir); db = Database(s.db_path); pipe = Pipeline(s, storage, db)
    assert pipe.save_raw(PlanPayload.model_validate(payload()))["status"] == "RAW"
    original = storage.plan_dir("e2e")/"raw/original.json"; before = original.read_bytes()
    first = pipe.process("e2e")
    assert first["status"] == "PROCESSED" and first["summary"] == {"rooms": 1, "floorAreaM2": 6.0}
    assert first["files"]["glb"] is None
    required = {"processed-plan.json", "plan.dxf", "plan.svg", "preview.png", "plan.pdf", "plan3d.json", "manifest.json"}
    assert required <= {p.name for p in (storage.plan_dir("e2e")/"current").iterdir()}
    manifest = json.loads((storage.plan_dir("e2e")/"current/manifest.json").read_text())
    assert manifest["status"] == "PROCESSED" and manifest["createdAt"] and manifest["completedAt"]
    second = pipe.process("e2e")
    assert second["version"] == 2 and original.read_bytes() == before
    assert (storage.plan_dir("e2e")/"versions/001/plan.dxf").exists()
    assert (storage.plan_dir("e2e")/"versions/002/plan.dxf").exists()


def test_generated_plan_id_and_job_dedup(tmp_path: Path):
    s = cfg(tmp_path); pipe = Pipeline(s, PlanStorage(s.data_dir), Database(s.db_path))
    created = pipe.save_raw(PlanPayload.model_validate(payload(None)))
    assert len(created["planId"]) == 32
    pipe.save_raw(PlanPayload.model_validate(payload("dedupe")))
    real = pipe.process
    def slow(pid): time.sleep(.15); return real(pid)
    pipe.process = slow  # type: ignore[method-assign]
    jobs = JobManager(pipe, 2); a = jobs.submit("dedupe"); b = jobs.submit("dedupe")
    assert a["status"] == "QUEUED" and a["created"] is True
    assert b["created"] is False and b["jobId"] == a["jobId"]


def test_fastapi_polling_versions_files_security_and_cors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GE360_API_KEY", "api-test")
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path/"api")); monkeypatch.setenv("GE360_DB_PATH", str(tmp_path/"api/db.sqlite3"))
    monkeypatch.setenv("GE360_AI_ENABLED", "false"); monkeypatch.setenv("GE360_CORS_ORIGINS", "https://app.ge360.test,http://localhost")
    import backend.main as main
    main = importlib.reload(main); client = TestClient(main.app); h = {"X-GE360-API-Key": "api-test"}
    assert client.get("/api/v1/health").status_code == 401
    viewer = client.get("/viewer3d/")
    assert viewer.status_code == 200 and "GE360 3D Viewer" in viewer.text
    assert client.post("/api/v1/plans", json=payload("api1"), headers=h).json()["status"] == "RAW"
    queued = client.post("/api/v1/plans/api1/process", headers=h).json()
    assert queued["status"] == "QUEUED" and wait_job(client, queued["jobId"], h)["status"] == "DONE"
    status = client.get("/api/v1/plans/api1", headers=h).json()
    assert status["status"] == "PROCESSED" and status["currentVersion"] == 1
    assert status["summary"] == {"rooms": 1, "floorAreaM2": 6.0} and status["files"]["glb"] is None
    for route in ("processed", "preview", "png", "svg", "pdf", "dxf", "3d"):
        assert client.get(f"/api/v1/plans/api1/{route}", headers=h).status_code == 200
    q2 = client.post("/api/v1/plans/api1/reprocess", headers=h).json(); assert wait_job(client, q2["jobId"], h)["status"] == "DONE"
    versions = client.get("/api/v1/plans/api1/versions", headers=h).json()
    assert [v["version"] for v in versions] == [2, 1] and all(v["quality"] == "OK" for v in versions)
    assert client.get("/api/v1/plans/api1/versions/1/pdf", headers=h).content.startswith(b"%PDF")
    cors = client.options("/api/v1/plans", headers={"Origin": "https://app.ge360.test", "Access-Control-Request-Method": "POST"})
    assert cors.headers["access-control-allow-origin"] == "https://app.ge360.test"


def test_empty_api_key_is_blocked_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GE360_API_KEY", "")
    monkeypatch.setenv("GE360_API_KEY_FILE", str(tmp_path/"missing.key"))
    monkeypatch.setenv("GE360_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path/"dev"))
    monkeypatch.setenv("GE360_DB_PATH", str(tmp_path/"dev/db.sqlite3"))
    import backend.main as main
    with pytest.raises(RuntimeError, match="API key required"):
        importlib.reload(main)


def test_explicit_development_mode_can_disable_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GE360_API_KEY", "")
    monkeypatch.setenv("GE360_API_KEY_FILE", str(tmp_path/"missing.key"))
    monkeypatch.setenv("GE360_REQUIRE_API_KEY", "false")
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path/"dev2"))
    monkeypatch.setenv("GE360_DB_PATH", str(tmp_path/"dev2/db.sqlite3"))
    import backend.main as main
    main = importlib.reload(main)
    client = TestClient(main.app)
    assert client.get("/api/v1/health").json()["apiKeyRequired"] is False
    assert client.post("/api/v1/plans", json=payload(None)).json()["status"] == "RAW"
