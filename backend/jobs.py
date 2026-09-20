from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from backend.models import PlanStatus
from backend.pipeline import Pipeline


class JobManager:
    """Small in-process queue with one active job per plan.

    V1 deliberately avoids Redis/Celery and assumes one backend process owns the
    in-process queue. The interface is isolated so an external worker can replace
    it later without changing the HTTP contract.
    """

    def __init__(self, pipeline: Pipeline, max_workers: int = 2):
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix="ge360-rilievi"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, Future] = {}
        self._job_plan: dict[str, str] = {}
        self._active_by_plan: dict[str, str] = {}

    def submit(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            active_id = self._active_by_plan.get(plan_id)
            if active_id is not None:
                active = self._jobs.get(active_id)
                if active is not None and not active.done():
                    row = self.pipeline.db.get(plan_id) or {}
                    return {
                        "jobId": active_id,
                        "status": row.get("status", PlanStatus.QUEUED.value),
                        "created": False,
                    }

            row = self.pipeline.db.get(plan_id)
            if row and row["status"] in {PlanStatus.QUEUED.value, PlanStatus.PROCESSING.value}:
                # No local Future owns this plan, so this state survived a service
                # restart/crash. An explicit process/reprocess request is allowed
                # to recover it. This is safe for the V1 single-process worker
                # model and avoids plans remaining stuck forever.
                self.pipeline.storage.append_log(
                    plan_id,
                    {
                        "event": "orphaned_job_recovered",
                        "previousStatus": row["status"],
                    },
                )
                self.pipeline.db.set_status(
                    plan_id,
                    PlanStatus.ERROR,
                    error=f"interrupted {row['status'].lower()} job recovered before requeue",
                )

            job_id = str(uuid.uuid4())
            self.pipeline.db.set_status(plan_id, PlanStatus.QUEUED, error="")
            self._active_by_plan[plan_id] = job_id
            self._job_plan[job_id] = plan_id
            try:
                future = self.executor.submit(self.pipeline.process, plan_id)
            except Exception:
                self._active_by_plan.pop(plan_id, None)
                self._job_plan.pop(job_id, None)
                self.pipeline.db.set_status(plan_id, PlanStatus.ERROR, error="failed to queue job")
                raise
            self._jobs[job_id] = future
            future.add_done_callback(lambda _future, jid=job_id, pid=plan_id: self._finish(jid, pid))
            return {"jobId": job_id, "status": PlanStatus.QUEUED.value, "created": True}

    def _finish(self, job_id: str, plan_id: str) -> None:
        with self._lock:
            if self._active_by_plan.get(plan_id) == job_id:
                self._active_by_plan.pop(plan_id, None)

    def state(self, job_id: str) -> dict | None:
        with self._lock:
            future = self._jobs.get(job_id)
            plan_id = self._job_plan.get(job_id)
        if future is None or plan_id is None:
            return None
        if not future.done():
            row = self.pipeline.db.get(plan_id) or {}
            return {
                "jobId": job_id,
                "planId": plan_id,
                "status": row.get("status", PlanStatus.QUEUED.value),
            }
        try:
            result = future.result()
            return {
                "jobId": job_id,
                "planId": plan_id,
                "status": "DONE",
                "result": result,
            }
        except Exception as exc:
            return {"jobId": job_id, "planId": plan_id, "status": "ERROR", "error": str(exc)}
