from __future__ import annotations
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from backend.models import PlanStatus

SCHEMA='''
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
'''
class Database:
    def __init__(self,path:Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as con:con.execute(SCHEMA)
    def connect(self):
        con=sqlite3.connect(self.path,check_same_thread=False);con.row_factory=sqlite3.Row;return con
    def upsert_raw(self,plan_id:str,name:str,path:Path)->None:
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            con.execute('''INSERT INTO plans(plan_id,name,created_at,updated_at,status,current_version,path)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET name=excluded.name,updated_at=excluded.updated_at,status=excluded.status,path=excluded.path''',(plan_id,name,now,now,PlanStatus.RAW.value,0,str(path)));con.commit()
    def set_status(self,plan_id:str,status:PlanStatus,*,version:int|None=None,quality:dict|None=None,needs_review:bool|None=None,error:str|None=None)->None:
        now=datetime.now(timezone.utc).isoformat();fields=['status=?','updated_at=?'];vals=[status.value,now]
        if version is not None:fields.append('current_version=?');vals.append(version)
        if quality is not None:fields.append('quality_json=?');vals.append(json.dumps(quality,ensure_ascii=False))
        if needs_review is not None:fields.append('needs_review=?');vals.append(1 if needs_review else 0)
        if error is not None:fields.append('last_error=?');vals.append(error)
        vals.append(plan_id)
        with self.connect() as con:con.execute(f"UPDATE plans SET {', '.join(fields)} WHERE plan_id=?",vals);con.commit()
    def get(self,plan_id:str)->dict|None:
        with self.connect() as con:row=con.execute('SELECT * FROM plans WHERE plan_id=?',(plan_id,)).fetchone()
        if not row:return None
        out=dict(row);out['needsReview']=bool(out.pop('needs_review'));q=out.pop('quality_json');out['quality']=json.loads(q) if q else None;return out
