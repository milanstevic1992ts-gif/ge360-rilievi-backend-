from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import PlanRecord, PlanStatus


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
    error TEXT
);
"""


class PlanDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def upsert_raw(self, plan_id: str, name: str, path: str) -> PlanRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            row = con.execute("SELECT created_at, current_version FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            created = row["created_at"] if row else now
            version = int(row["current_version"]) if row else 0
            con.execute(
                """INSERT INTO plans(plan_id,name,created_at,updated_at,status,current_version,path,quality_json,needs_review,error)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(plan_id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at,
                   status=excluded.status,path=excluded.path,error=NULL""",
                (plan_id, name, created, now, PlanStatus.RAW.value, version, path, None, 0, None),
            )
        return self.get(plan_id)

    def set_status(
        self,
        plan_id: str,
        status: PlanStatus,
        *,
        current_version: int | None = None,
        quality: dict | None = None,
        needs_review: bool | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        fields = ["updated_at=?", "status=?", "error=?"]
        params: list[object] = [now, status.value, error]
        if current_version is not None:
            fields.append("current_version=?")
            params.append(current_version)
        if quality is not None:
            fields.append("quality_json=?")
            params.append(json.dumps(quality, ensure_ascii=False))
        if needs_review is not None:
            fields.append("needs_review=?")
            params.append(1 if needs_review else 0)
        params.append(plan_id)
        with self.connect() as con:
            con.execute(f"UPDATE plans SET {', '.join(fields)} WHERE plan_id=?", params)

    def get(self, plan_id: str) -> PlanRecord:
        with self.connect() as con:
            row = con.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            raise KeyError(plan_id)
        return PlanRecord(
            planId=row["plan_id"],
            name=row["name"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
            status=PlanStatus(row["status"]),
            currentVersion=int(row["current_version"]),
            path=row["path"],
            quality=json.loads(row["quality_json"]) if row["quality_json"] else None,
            needsReview=bool(row["needs_review"]),
            error=row["error"],
        )
