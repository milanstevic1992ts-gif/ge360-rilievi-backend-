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
        "http://127.0.0.1:11434", "qwen2.5:7b", .1,
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


def test_orphaned_processing_state_can_be_requeued_after_restart(tmp_path: Path):
    settings = _settings(tmp_path)
    storage = PlanStorage(settings.data_dir)
    db = Database(settings.db_path)
    pipeline = Pipeline(settings, storage, db)
    pipeline.save_raw(_payload())

    # Simulate a process dying after persisting PROCESSING but before a local
    # Future can survive the restart.
    db.set_status("restart-recovery", PlanStatus.PROCESSING, error="")
    jobs = JobManager(pipeline, max_workers=1)

    queued = jobs.submit("restart-recovery")
    assert queued["created"] is True
    assert queued["status"] == "QUEUED"
    assert queued["jobId"]

    for _ in range(250):
        state = jobs.state(queued["jobId"])
        if state and state["status"] in {"DONE", "ERROR"}:
            break
        time.sleep(.02)
    else:
        raise AssertionError("recovered job timeout")

    assert state["status"] == "DONE", state
    assert db.get("restart-recovery")["status"] == "PROCESSED"
    log = (storage.plan_dir("restart-recovery") / "logs/processing.jsonl").read_text(encoding="utf-8")
    assert '"event":"orphaned_job_recovered"' in log
    assert '"previousStatus":"PROCESSING"' in log
