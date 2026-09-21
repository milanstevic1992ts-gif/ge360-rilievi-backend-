from __future__ import annotations

import time
from pathlib import Path

from backend.config import Settings
from backend.db import Database
from backend.jobs import JobManager
from backend.models import PlanPayload, PlanStatus
from backend.pipeline import Pipeline
from backend.storage import PlanStorage


def _wall(i, a, b, cm):
    return {"id": i, "a": {"x": a[0], "y": a[1]}, "b": {"x": b[0], "y": b[1]}, "lengthCm": cm}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        "", tmp_path / "data", tmp_path / "data/db.sqlite3", "127.0.0.1", 9888,
        120, 2700, 250, 25, .5, False,
        "http://127.0.0.1:11434", "qwen3:8b", .1,
        require_api_key=False,
    )


def _payload():
    return PlanPayload.model_validate({
        "version": 4,
        "planId": "restart-recovery",
        "walls": [
            _wall("w1", (0, 0), (200, 0), 200),
            _wall("w2", (200, 0), (200, 300), 300),
            _wall("w3", (200, 300), (0, 300), 200),
            _wall("w4", (0, 300), (0, 0), 300),
        ],
    })


def _wait(jobs: JobManager, job_id: str):
    for _ in range(300):
        state = jobs.state(job_id)
        if state and state["status"] in {"DONE", "ERROR"}:
            return state
        time.sleep(.02)
    raise AssertionError("recovered job timeout")


def test_processing_job_is_persisted_and_resumed_automatically(tmp_path: Path):
    settings = _settings(tmp_path)
    storage = PlanStorage(settings.data_dir)
    db = Database(settings.db_path)
    pipeline = Pipeline(settings, storage, db)
    pipeline.save_raw(_payload())

    job, created = db.create_or_get_active_job("restart-recovery")
    assert created
    db.set_job_status(job["jobId"], "PROCESSING")
    db.set_status("restart-recovery", PlanStatus.PROCESSING, error="")

    # A fresh JobManager represents the new process after a crash/restart.
    jobs = JobManager(Pipeline(settings, PlanStorage(settings.data_dir), Database(settings.db_path)), max_workers=1)
    state = _wait(jobs, job["jobId"])
    assert state["status"] == "DONE", state
    assert state["attempts"] >= 2
    assert db.get("restart-recovery")["status"] == "PROCESSED"
    log = (storage.plan_dir("restart-recovery") / "logs/processing.jsonl").read_text(encoding="utf-8")
    assert '"event":"persistent_job_recovered"' in log


def test_job_state_survives_new_manager_instance(tmp_path: Path):
    settings = _settings(tmp_path)
    storage = PlanStorage(settings.data_dir)
    db = Database(settings.db_path)
    pipeline = Pipeline(settings, storage, db)
    pipeline.save_raw(_payload())
    jobs = JobManager(pipeline, max_workers=1)
    queued = jobs.submit("restart-recovery")
    state = _wait(jobs, queued["jobId"])
    assert state["status"] == "DONE"
    jobs.shutdown()

    jobs2 = JobManager(Pipeline(settings, storage, Database(settings.db_path)), max_workers=1)
    persisted = jobs2.state(queued["jobId"])
    assert persisted and persisted["status"] == "DONE"
    assert persisted["result"]["planId"] == "restart-recovery"
