from __future__ import annotations
import json
from datetime import datetime,timezone
from typing import Any
from backend.storage import PlanStorage
_SECRET=("password","passwd","token","api_key","apikey","authorization","secret","credential")
def _clean(v:Any)->Any:
    if isinstance(v,dict): return {str(k):("[REDACTED]" if any(x in str(k).lower() for x in _SECRET) else _clean(xv)) for k,xv in v.items()}
    if isinstance(v,list): return [_clean(x) for x in v]
    return v
class AIAuditLog:
    def __init__(self,storage:PlanStorage): self.storage=storage
    def append(self,plan_id:str,event:dict[str,Any]):
        p=self.storage.ensure(plan_id)/"logs"/"ai-audit.jsonl"
        row={"timestamp":datetime.now(timezone.utc).isoformat(),**_clean(event)}
        with p.open("a",encoding="utf-8") as f: f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
