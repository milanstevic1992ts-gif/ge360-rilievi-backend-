from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.models import PlanStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
 plan_id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 status TEXT NOT NULL,
 current_version INTEGER NOT NULL DEFAULT 0,
 path TEXT NOT NULL,
 quality_json TEXT,
 needs_review INTEGER NOT NULL DEFAULT 0,
 last_error TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL,
 status TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 input_hash TEXT,
 raw_json TEXT,
 result_json TEXT,
 error TEXT,
 FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_plan ON jobs(plan_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_processing_plan
ON jobs(plan_id)
WHERE status='PROCESSING';

CREATE TABLE IF NOT EXISTS plan_media (
 media_id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL,
 target_type TEXT NOT NULL,
 target_id TEXT,
 caption TEXT,
 mime_type TEXT NOT NULL,
 filename TEXT NOT NULL,
 path TEXT NOT NULL,
 size_bytes INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
);
CREATE INDEX IF NOT EXISTS idx_plan_media_plan ON plan_media(plan_id, created_at DESC);
"""

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)
            columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)").fetchall()}
            if "input_hash" not in columns:
                con.execute("ALTER TABLE jobs ADD COLUMN input_hash TEXT")
            if "raw_json" not in columns:
                con.execute("ALTER TABLE jobs ADD COLUMN raw_json TEXT")
            con.execute("DROP INDEX IF EXISTS idx_jobs_one_active_plan")
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_processing_plan "
                "ON jobs(plan_id) WHERE status='PROCESSING'"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_hash "
                "ON jobs(plan_id, input_hash, created_at DESC)"
            )
            con.commit()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def upsert_raw(self, plan_id: str, name: str, path: Path) -> None:
        now = _utcnow()
        with self.connect() as con:
            con.execute(
                """INSERT INTO plans(plan_id,name,created_at,updated_at,status,current_version,path)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(plan_id) DO UPDATE SET
                  name=excluded.name,
                  updated_at=excluded.updated_at,
                  status=excluded.status,
                  path=excluded.path,
                  quality_json=NULL,
                  needs_review=0,
                  last_error=NULL""",
                (plan_id, name, now, now, PlanStatus.RAW.value, 0, str(path)),
            )
            con.commit()

    def set_status(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        version: int | None = None,
        quality: dict | None = None,
        needs_review: bool | None = None,
        error: str | None = None,
    ) -> None:
        now = _utcnow()
        fields = ["status=?", "updated_at=?"]
        vals: list[object] = [status.value, now]
        if version is not None:
            fields.append("current_version=?")
            vals.append(version)
        if quality is not None:
            fields.append("quality_json=?")
            vals.append(json.dumps(quality, ensure_ascii=False))
        if needs_review is not None:
            fields.append("needs_review=?")
            vals.append(1 if needs_review else 0)
        if error is not None:
            fields.append("last_error=?")
            vals.append(error)
        vals.append(plan_id)
        with self.connect() as con:
            con.execute(f"UPDATE plans SET {', '.join(fields)} WHERE plan_id=?", vals)
            con.commit()

    def get(self, plan_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["needsReview"] = bool(out.pop("needs_review"))
        q = out.pop("quality_json")
        out["quality"] = json.loads(q) if q else None
        return out

    # ---------------- persistent jobs ----------------

    def create_or_get_active_job(self, plan_id: str) -> tuple[dict, bool]:
        now = _utcnow()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            active = con.execute(
                "SELECT * FROM jobs WHERE plan_id=? AND status IN ('QUEUED','PROCESSING') ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
            if active:
                con.commit()
                return self._job_row(active), False
            job_id = str(uuid.uuid4())
            con.execute(
                "INSERT INTO jobs(job_id,plan_id,status,created_at,updated_at,attempts) VALUES(?,?,?,?,?,0)",
                (job_id, plan_id, "QUEUED", now, now),
            )
            con.commit()
        return self.get_job(job_id) or {"jobId": job_id, "planId": plan_id, "status": "QUEUED"}, True

    def create_or_get_revision_job(self, plan_id: str, input_hash: str, raw_payload: dict) -> tuple[dict, bool]:
        """Create one persistent job per distinct RAW revision."""
        now = _utcnow()
        raw_json = json.dumps(raw_payload, ensure_ascii=False, separators=(",", ":"))
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            active = con.execute(
                """SELECT * FROM jobs
                   WHERE plan_id=? AND input_hash=? AND status IN ('QUEUED','PROCESSING')
                   ORDER BY created_at DESC LIMIT 1""",
                (plan_id, input_hash),
            ).fetchone()
            if active:
                con.commit()
                return self._job_row(active), False
            job_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO jobs(job_id,plan_id,status,created_at,updated_at,attempts,input_hash,raw_json)
                   VALUES(?,?,?,?,?,0,?,?)""",
                (job_id, plan_id, "QUEUED", now, now, input_hash, raw_json),
            )
            con.commit()
        return self.get_job(job_id) or {
            "jobId": job_id, "planId": plan_id, "status": "QUEUED", "inputHash": input_hash
        }, True

    def next_queued_job(self, plan_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM jobs WHERE plan_id=? AND status='QUEUED' ORDER BY created_at ASC LIMIT 1",
                (plan_id,),
            ).fetchone()
        return self._job_row(row) if row else None

    def queued_plan_ids(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT plan_id FROM jobs WHERE status='QUEUED' ORDER BY plan_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def get_job_raw(self, job_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT raw_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or not row["raw_json"]:
            return None
        return json.loads(row["raw_json"])

    def requeue_interrupted_jobs(self) -> list[dict]:
        now = _utcnow()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = con.execute(
                "SELECT * FROM jobs WHERE status IN ('QUEUED','PROCESSING') ORDER BY created_at ASC"
            ).fetchall()
            for row in rows:
                if row["status"] == "PROCESSING":
                    con.execute(
                        "UPDATE jobs SET status='QUEUED', updated_at=?, attempts=attempts+1, error=? WHERE job_id=?",
                        (now, "worker interrupted; automatically requeued after restart", row["job_id"]),
                    )
            con.commit()
        return [self.get_job(row["job_id"]) for row in rows if self.get_job(row["job_id"])]

    def set_job_status(self, job_id: str, status: str, *, result: dict | None = None, error: str | None = None) -> None:
        now = _utcnow()
        fields = ["status=?", "updated_at=?"]
        vals: list[object] = [status, now]
        if status == "PROCESSING":
            fields.append("attempts=attempts+1")
        if result is not None:
            fields.append("result_json=?")
            vals.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            fields.append("error=?")
            vals.append(error)
        vals.append(job_id)
        with self.connect() as con:
            con.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id=?", vals)
            con.commit()

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def active_job_for_plan(self, plan_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM jobs WHERE plan_id=? AND status IN ('QUEUED','PROCESSING') ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        return self._job_row(row) if row else None

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict:
        out = dict(row)
        result_raw = out.pop("result_json")
        input_hash = out.pop("input_hash", None)
        out.pop("raw_json", None)
        return {
            "jobId": out.pop("job_id"),
            "planId": out.pop("plan_id"),
            "status": out.pop("status"),
            "createdAt": out.pop("created_at"),
            "updatedAt": out.pop("updated_at"),
            "attempts": int(out.pop("attempts") or 0),
            "inputHash": input_hash,
            "result": json.loads(result_raw) if result_raw else None,
            "error": out.pop("error"),
        }


# ---------------- plan photos / evidence ----------------

def _db_add_media(self, *, media_id: str, plan_id: str, target_type: str, target_id: str | None,
                  caption: str | None, mime_type: str, filename: str, path: str, size_bytes: int) -> dict:
    now = _utcnow()
    with self.connect() as con:
        con.execute(
            """INSERT INTO plan_media(media_id,plan_id,target_type,target_id,caption,mime_type,filename,path,size_bytes,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (media_id, plan_id, target_type, target_id, caption, mime_type, filename, path, int(size_bytes), now),
        )
        con.commit()
    return self.get_media(media_id) or {}

def _db_get_media(self, media_id: str) -> dict | None:
    with self.connect() as con:
        row = con.execute("SELECT * FROM plan_media WHERE media_id=?", (media_id,)).fetchone()
    return dict(row) if row else None

def _db_list_media(self, plan_id: str) -> list[dict]:
    with self.connect() as con:
        rows = con.execute("SELECT * FROM plan_media WHERE plan_id=? ORDER BY created_at ASC", (plan_id,)).fetchall()
    return [dict(row) for row in rows]

def _db_delete_media(self, media_id: str) -> dict | None:
    with self.connect() as con:
        row = con.execute("SELECT * FROM plan_media WHERE media_id=?", (media_id,)).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM plan_media WHERE media_id=?", (media_id,))
        con.commit()
    return dict(row)

Database.add_media = _db_add_media
Database.get_media = _db_get_media
Database.list_media = _db_list_media
Database.delete_media = _db_delete_media
