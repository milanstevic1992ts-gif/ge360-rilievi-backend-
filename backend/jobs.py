from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from backend.models import PlanStatus
from backend.pipeline import Pipeline


class JobManager:
    """Persistent SQLite-backed, revision-aware worker queue.

    SQLite owns job identity and RAW snapshots. Different revisions of the same
    plan may be QUEUED together, but exactly one revision per plan is PROCESSING.
    This prevents a new /refine from being swallowed by an older running job.
    """

    def __init__(self, pipeline: Pipeline, max_workers: int = 2):
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix="ge360-rilievi"
        )
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._active_plans: set[str] = set()
        self._recover()

    def _recover(self) -> None:
        recovered = self.pipeline.db.requeue_interrupted_jobs()
        for job in recovered:
            self.pipeline.storage.append_log(
                job["planId"],
                {
                    "event": "persistent_job_recovered",
                    "jobId": job["jobId"],
                    "attempts": job["attempts"],
                    "inputHash": job.get("inputHash"),
                },
            )
        for plan_id in self.pipeline.db.queued_plan_ids():
            self._schedule_next(plan_id)

    def submit(self, plan_id: str) -> dict[str, Any]:
        if not self.pipeline.db.get(plan_id):
            raise ValueError("Plan not found")
        raw_snapshot = self.pipeline.storage.raw_payload(plan_id)
        input_hash = self.pipeline.storage.sha256_json(raw_snapshot)
        job, created = self.pipeline.db.create_or_get_revision_job(plan_id, input_hash, raw_snapshot)
        if created:
            self.pipeline.storage.append_log(
                plan_id,
                {"event": "revision_queued", "jobId": job["jobId"], "inputHash": input_hash},
            )
            self._schedule_next(plan_id)
        return {
            "jobId": job["jobId"],
            "status": job["status"],
            "created": created,
            "inputHash": job.get("inputHash") or input_hash,
        }

    def _schedule_next(self, plan_id: str) -> None:
        with self._lock:
            if plan_id in self._active_plans:
                return
            job = self.pipeline.db.next_queued_job(plan_id)
            if not job:
                return
            job_id = job["jobId"]
            self._active_plans.add(plan_id)
            self.pipeline.db.set_status(plan_id, PlanStatus.QUEUED, error="")
            try:
                future = self.executor.submit(self._run, job_id, plan_id)
            except Exception:
                self._active_plans.discard(plan_id)
                self.pipeline.db.set_job_status(job_id, "ERROR", error="failed to queue job")
                self.pipeline.db.set_status(plan_id, PlanStatus.ERROR, error="failed to queue job")
                raise
            self._futures[job_id] = future
            future.add_done_callback(lambda _f, jid=job_id, pid=plan_id: self._finish(jid, pid))

    def _run(self, job_id: str, plan_id: str):
        self.pipeline.db.set_job_status(job_id, "PROCESSING", error="")
        self.pipeline.db.set_status(plan_id, PlanStatus.PROCESSING, error="")
        raw_snapshot = self.pipeline.db.get_job_raw(job_id)
        if raw_snapshot is None:
            # Backward compatibility for jobs created before revision snapshots
            # existed. New jobs always have raw_json persisted.
            raw_snapshot = self.pipeline.storage.raw_payload(plan_id)
        try:
            result = self.pipeline.process(plan_id, raw_override=raw_snapshot)
        except Exception as exc:
            self.pipeline.db.set_job_status(job_id, "ERROR", error=str(exc))
            raise
        self.pipeline.db.set_job_status(job_id, "DONE", result=result, error="")
        return result

    def _finish(self, job_id: str, plan_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)
            self._active_plans.discard(plan_id)
        # Always continue with the next saved revision, even if the previous
        # revision failed.
        self._schedule_next(plan_id)

    def state(self, job_id: str) -> dict | None:
        return self.pipeline.db.get_job(job_id)

    def shutdown(self, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)
