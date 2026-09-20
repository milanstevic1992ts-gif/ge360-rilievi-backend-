from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PlanStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def plan_dir(self, plan_id: str) -> Path:
        safe = "".join(c for c in plan_id if c.isalnum() or c in "-_" )
        if not safe or safe != plan_id:
            raise ValueError("invalid planId")
        return self.root / safe

    def ensure(self, plan_id: str) -> Path:
        base = self.plan_dir(plan_id)
        for part in ("raw", "current", "versions", "logs"):
            (base / part).mkdir(parents=True, exist_ok=True)
        return base

    def save_raw(self, plan_id: str, payload: dict[str, Any]) -> Path:
        base = self.ensure(plan_id)
        original = base / "raw" / "original.json"
        latest = base / "raw" / "latest.json"
        if not original.exists():
            self.write_json_atomic(original, payload)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            self.write_json_atomic(base / "raw" / f"received-{stamp}.json", payload)
        self.write_json_atomic(latest, payload)
        return latest

    def raw_payload(self, plan_id: str) -> dict[str, Any]:
        raw_dir = self.plan_dir(plan_id) / "raw"
        path = raw_dir / "latest.json"
        if not path.exists():
            path = raw_dir / "original.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def next_version(self, plan_id: str) -> int:
        versions = self.plan_dir(plan_id) / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        nums = [int(p.name) for p in versions.iterdir() if p.is_dir() and p.name.isdigit()]
        return (max(nums) if nums else 0) + 1

    def version_dir(self, plan_id: str, version: int) -> Path:
        path = self.ensure(plan_id) / "versions" / f"{version:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def publish_current(self, plan_id: str, version_dir: Path) -> None:
        current = self.ensure(plan_id) / "current"
        for p in current.iterdir():
            if p.is_file() or p.is_symlink():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        for source in version_dir.iterdir():
            if source.is_file():
                shutil.copy2(source, current / source.name)

    def append_log(self, plan_id: str, event: dict[str, Any]) -> None:
        path = self.ensure(plan_id) / "logs" / "processing.jsonl"
        row = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def write_json_atomic(path: Path, data: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def sha256_json(data: Any) -> str:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()
