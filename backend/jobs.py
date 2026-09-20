from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor

from backend.pipeline import Pipeline


class JobManager:
    """Small in-process worker. Interface intentionally isolated for future RQ/Celery replacement."""
    def __init__(self, pipeline: Pipeline, max_workers: int = 2):
        self.pipeline = pipeline
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ge360-rilievi")
        self._lock = threading.Lock()
        self._jobs: dict[str, Future] = {}

    def submit(self, plan_id: str) -> str:
        job_id = str(uuid.uuid4())
        future = self.executor.submit(self.pipeline.process, plan_id)
        with self._lock:
            self._jobs[job_id] = future
        return job_id

    def state(self, job_id: str) -> dict | None:
        with self._lock:
            future = self._jobs.get(job_id)
        if future is None:
            return None
        if not future.done():
            return {"jobId":job_id,"status":"PROCESSING"}
        try:
            return {"jobId":job_id,"status":"DONE","result":future.result()}
        except Exception as exc:
            return {"jobId":job_id,"status":"ERROR","error":str(exc)}
