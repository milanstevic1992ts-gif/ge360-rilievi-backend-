from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PlanStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def plan_dir(self, plan_id: str) -> Path:
        safe = "".join(c for c in plan_id if c.isalnum() or c in "-_")
        if not safe or safe != plan_id:
            raise ValueError("invalid planId")
        return self.root / safe

    def ensure(self, plan_id: str) -> Path:
        base = self.plan_dir(plan_id)
        for sub in ("raw", "current", "versions", "logs"):
            (base / sub).mkdir(parents=True, exist_ok=True)
        return base

    def save_raw(self, plan_id: str, payload: dict[str, Any]) -> Path:
        base = self.ensure(plan_id)
        target = base / "raw" / "original.json"
        if target.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            shutil.copy2(target, base / "raw" / f"original-{ts}.json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def load_raw(self, plan_id: str) -> dict[str, Any]:
        target = self.plan_dir(plan_id) / "raw" / "original.json"
        return json.loads(target.read_text(encoding="utf-8"))

    def next_version(self, plan_id: str) -> int:
        versions = self.ensure(plan_id) / "versions"
        nums = [int(p.name) for p in versions.iterdir() if p.is_dir() and p.name.isdigit()]
        return max(nums, default=0) + 1

    def version_dir(self, plan_id: str, version: int) -> Path:
        path = self.ensure(plan_id) / "versions" / f"{version:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def publish_current(self, plan_id: str, version: int) -> None:
        src = self.version_dir(plan_id, version)
        dst = self.ensure(plan_id) / "current"
        for child in dst.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        for item in src.iterdir():
            if item.is_file():
                shutil.copy2(item, dst / item.name)

    def current_file(self, plan_id: str, filename: str) -> Path:
        return self.plan_dir(plan_id) / "current" / filename

    def versions(self, plan_id: str) -> list[dict[str, Any]]:
        base = self.ensure(plan_id) / "versions"
        out = []
        for p in sorted(base.iterdir()):
            if not p.is_dir() or not p.name.isdigit():
                continue
            out.append({"version": int(p.name), "files": sorted(x.name for x in p.iterdir() if x.is_file())})
        return out

    def append_log(self, plan_id: str, event: dict[str, Any]) -> None:
        event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        path = self.ensure(plan_id) / "logs" / "processing.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def hash_payload(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
