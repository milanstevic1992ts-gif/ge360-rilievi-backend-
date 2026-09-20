from __future__ import annotations
import hashlib,json,shutil
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
class PlanStorage:
    def __init__(self,root:Path):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    def plan_dir(self,plan_id:str)->Path:
        safe=''.join(c for c in plan_id if c.isalnum() or c in '-_')
        if not safe or safe!=plan_id:raise ValueError('invalid planId')
        return self.root/safe
    def ensure(self,plan_id:str)->Path:
        base=self.plan_dir(plan_id)
        for part in ('raw','current','versions','logs'):(base/part).mkdir(parents=True,exist_ok=True)
        return base
    def save_raw(self,plan_id:str,payload:dict[str,Any])->Path:
        base=self.ensure(plan_id);original=base/'raw/original.json';latest=base/'raw/latest.json'
        if not original.exists():self.write_json_atomic(original,payload)
        else:
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');self.write_json_atomic(base/'raw'/f'received-{stamp}.json',payload)
        self.write_json_atomic(latest,payload);return latest
    def raw_payload(self,plan_id:str)->dict[str,Any]:
        p=self.plan_dir(plan_id)/'raw/latest.json'
        if not p.exists():p=self.plan_dir(plan_id)/'raw/original.json'
        return json.loads(p.read_text(encoding='utf-8'))
    def next_version(self,plan_id:str)->int:
        root=self.ensure(plan_id)/'versions';nums=[int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()];return (max(nums) if nums else 0)+1
    def version_dir(self,plan_id:str,version:int)->Path:
        p=self.ensure(plan_id)/'versions'/f'{version:03d}';p.mkdir(parents=True,exist_ok=True);return p
    def publish_current(self,plan_id:str,version_dir:Path)->None:
        current=self.ensure(plan_id)/'current'
        for p in current.iterdir():
            if p.is_dir():shutil.rmtree(p)
            else:p.unlink()
        for src in version_dir.iterdir():
            if src.is_file():shutil.copy2(src,current/src.name)
    def append_log(self,plan_id:str,event:dict[str,Any])->None:
        p=self.ensure(plan_id)/'logs/processing.jsonl';row={'ts':datetime.now(timezone.utc).isoformat(),**event}
        with p.open('a',encoding='utf-8') as fh:fh.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    @staticmethod
    def write_json_atomic(path:Path,data:Any)->None:
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    @staticmethod
    def sha256_json(data:Any)->str:
        raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode();return hashlib.sha256(raw).hexdigest()
