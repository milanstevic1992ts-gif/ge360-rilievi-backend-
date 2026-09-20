from __future__ import annotations
import hashlib,json,shutil
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
class PlanStorage:
    def __init__(self,root:Path):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    def plan_dir(self,plan_id):
        safe=''.join(c for c in plan_id if c.isalnum() or c in '-_')
        if not safe or safe!=plan_id:raise ValueError('invalid planId')
        return self.root/safe
    def ensure(self,plan_id):
        b=self.plan_dir(plan_id)
        for x in ('raw','current','versions','logs','candidates'):(b/x).mkdir(parents=True,exist_ok=True)
        return b
    def save_raw(self,plan_id,payload):
        b=self.ensure(plan_id);orig=b/'raw/original.json';latest=b/'raw/latest.json'
        if not orig.exists():self.write_json_atomic(orig,payload)
        else:self.write_json_atomic(b/'raw'/f"received-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json",payload)
        self.write_json_atomic(latest,payload);self.write_json_atomic(b/'raw/pending.json',{'inputHash':self.sha256_json(payload),'receivedAt':datetime.now(timezone.utc).isoformat()});return latest
    def raw_payload(self,plan_id):
        p=self.plan_dir(plan_id)/'raw/latest.json'
        if not p.exists():p=self.plan_dir(plan_id)/'raw/original.json'
        return json.loads(p.read_text(encoding='utf-8'))
    def authoritative_payload(self,plan_id):
        b=self.plan_dir(plan_id);current=b/'current/source-plan.json'
        if (b/'raw/pending.json').exists() or not current.exists():return self.raw_payload(plan_id),'raw'
        return json.loads(current.read_text(encoding='utf-8')),'authoritative'
    def mark_raw_consumed(self,plan_id):
        p=self.plan_dir(plan_id)/'raw/pending.json'
        if p.exists():p.unlink()
    def next_version(self,plan_id):
        root=self.ensure(plan_id)/'versions';nums=[int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()];return (max(nums) if nums else 0)+1
    def version_dir(self,plan_id,version):
        p=self.ensure(plan_id)/'versions'/f'{version:03d}';p.mkdir(parents=True,exist_ok=True);return p
    def publish_current(self,plan_id,version_dir):
        c=self.ensure(plan_id)/'current'
        for p in c.iterdir():shutil.rmtree(p) if p.is_dir() else p.unlink()
        for p in version_dir.iterdir():
            if p.is_file():shutil.copy2(p,c/p.name)
    def append_log(self,plan_id,event):
        p=self.ensure(plan_id)/'logs/processing.jsonl';row={'ts':datetime.now(timezone.utc).isoformat(),**event}
        with p.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    @staticmethod
    def write_json_atomic(path,data):
        path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    @staticmethod
    def sha256_json(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
