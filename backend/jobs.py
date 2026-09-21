from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from backend.models import PlanStatus
from backend.pipeline import Pipeline


class JobManager:
    """Persistent SQLite-backed worker queue.

    SQLite is authoritative for job identity/state. Futures only represent work
    owned by the current process. On process start, QUEUED jobs and jobs that
    died in PROCESSING are scheduled automatically.
    """

    def __init__(self, pipeline: Pipeline, max_workers: int = 2):
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix="ge360-rilievi"
        )
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._recover()

    def _recover(self) -> None:
        for job in self.pipeline.db.requeue_interrupted_jobs():
            plan_id = job["planId"]
            self.pipeline.storage.append_log(
                plan_id,
                {
                    "event": "persistent_job_recovered",
                    "jobId": job["jobId"],
                    "attempts": job["attempts"],
                },
            )
            self.pipeline.db.set_status(plan_id, PlanStatus.QUEUED, error="")
            self._schedule(job["jobId"], plan_id)

    def submit(self, plan_id: str) -> dict[str, Any]:
        row = self.pipeline.db.get(plan_id)
        if not row:
            raise ValueError("Plan not found")
        job, created = self.pipeline.db.create_or_get_active_job(plan_id)
        if not created:
            return {"jobId": job["jobId"], "status": job["status"], "created": False}

        self.pipeline.db.set_status(plan_id, PlanStatus.QUEUED, error="")
        try:
            self._schedule(job["jobId"], plan_id)
        except Exception:
            self.pipeline.db.set_job_status(job["jobId"], "ERROR", error="failed to queue job")
            self.pipeline.db.set_status(plan_id, PlanStatus.ERROR, error="failed to queue job")
            raise
        return {"jobId": job["jobId"], "status": "QUEUED", "created": True}

    def _schedule(self, job_id: str, plan_id: str) -> None:
        with self._lock:
            existing = self._futures.get(job_id)
            if existing is not None and not existing.done():
                return
            future = self.executor.submit(self._run, job_id, plan_id)
            self._futures[job_id] = future
            future.add_done_callback(lambda _f, jid=job_id: self._forget_future(jid))

    def _run(self, job_id: str, plan_id: str):
        self.pipeline.db.set_job_status(job_id, "PROCESSING", error="")
        self.pipeline.db.set_status(plan_id, PlanStatus.PROCESSING, error="")
        try:
            result = self.pipeline.process(plan_id)
        except Exception as exc:
            self.pipeline.db.set_job_status(job_id, "ERROR", error=str(exc))
            raise
        self.pipeline.db.set_job_status(job_id, "DONE", result=result, error="")
        return result

    def _forget_future(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)

    def state(self, job_id: str) -> dict | None:
        return self.pipeline.db.get_job(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)
