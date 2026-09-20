from __future__ import annotations
import json,re,sqlite3
from datetime import datetime,timezone
from pathlib import Path
_TOKEN=re.compile(r"[a-zA-ZÀ-ÿ0-9_]+")
def _tokens(s): return {x.casefold() for x in _TOKEN.findall(s) if len(x)>1}
class AICADMemory:
    def __init__(self,path:Path,enabled:bool=True):
        self.path=Path(path); self.enabled=enabled
        if enabled:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(self.path) as c:
                c.execute("""CREATE TABLE IF NOT EXISTS ai_examples(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT UNIQUE,plan_id TEXT,created_at TEXT,instruction TEXT,operations_json TEXT,planner_status TEXT,candidate_status TEXT,applied INTEGER DEFAULT 0,forced INTEGER DEFAULT 0)""")
    def remember_plan(self,request_id,plan_id,instruction,operations,planner_status="ready"):
        if not self.enabled:return
        with sqlite3.connect(self.path) as c:c.execute("""INSERT INTO ai_examples(request_id,plan_id,created_at,instruction,operations_json,planner_status) VALUES(?,?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET instruction=excluded.instruction,operations_json=excluded.operations_json,planner_status=excluded.planner_status""",(request_id,plan_id,datetime.now(timezone.utc).isoformat(),instruction[:4000],json.dumps(operations,ensure_ascii=False),planner_status))
    def mark_candidate(self,request_id,status):
        if self.enabled:
            with sqlite3.connect(self.path) as c:c.execute("UPDATE ai_examples SET candidate_status=? WHERE request_id=?",(status,request_id))
    def mark_applied(self,request_id,*,forced=False):
        if self.enabled:
            with sqlite3.connect(self.path) as c:c.execute("UPDATE ai_examples SET applied=1,forced=? WHERE request_id=?",(1 if forced else 0,request_id))
    def similar_examples(self,instruction,limit=4):
        if not self.enabled:return []
        q=_tokens(instruction)
        with sqlite3.connect(self.path) as c: rows=c.execute("SELECT instruction,operations_json,applied,forced FROM ai_examples WHERE planner_status='ready' ORDER BY applied DESC,id DESC LIMIT 200").fetchall()
        out=[]
        for ins,ops,applied,forced in rows:
            t=_tokens(ins); score=(len(q&t)/max(len(q|t),1))+(0.15 if applied else 0)-(0.05 if forced else 0)
            if score>=0.16:
                try: out.append({"instruction":ins,"operations":json.loads(ops),"accepted":bool(applied),"score":min(1.0,score)})
                except Exception: pass
        return sorted(out,key=lambda x:x["score"],reverse=True)[:limit]
