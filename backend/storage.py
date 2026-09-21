from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2

class PlanStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def plan_dir(self, plan_id: str) -> Path:
        safe = ''.join(c for c in plan_id if c.isalnum() or c in '-_')
        if not safe or safe != plan_id:
            raise ValueError('invalid planId')
        return self.root / safe

    def ensure(self, plan_id: str) -> Path:
        base = self.plan_dir(plan_id)
        for part in ('raw', 'current', 'versions', 'logs', 'media'):
            (base / part).mkdir(parents=True, exist_ok=True)
        return base

    def save_raw(self, plan_id: str, payload: dict[str, Any]) -> Path:
        base = self.ensure(plan_id)
        original = base / 'raw/original.json'
        latest = base / 'raw/latest.json'
        if not original.exists():
            self.write_json_atomic(original, payload)
        else:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            self.write_json_atomic(base / 'raw' / f'received-{stamp}.json', payload)
        self.write_json_atomic(latest, payload)
        return latest

    def raw_payload(self, plan_id: str) -> dict[str, Any]:
        p = self.plan_dir(plan_id) / 'raw/latest.json'
        if not p.exists():
            p = self.plan_dir(plan_id) / 'raw/original.json'
        return json.loads(p.read_text(encoding='utf-8'))

    def next_version(self, plan_id: str) -> int:
        root = self.ensure(plan_id) / 'versions'
        nums = [int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
        return (max(nums) if nums else 0) + 1

    def version_dir(self, plan_id: str, version: int) -> Path:
        p = self.ensure(plan_id) / 'versions' / f'{version:03d}'
        p.mkdir(parents=True, exist_ok=True)
        return p

    def publish_current(self, plan_id: str, version_dir: Path) -> None:
        """Publish a fully written version with an atomic directory exchange.

        The current directory is never cleared in place. We build a sibling
        staging directory, fsync its files, then Linux renameat2(RENAME_EXCHANGE)
        swaps current and staging in one atomic VFS operation. A crash before the
        exchange leaves the old current untouched; a crash after it leaves the
        new current complete.
        """
        base = self.ensure(plan_id)
        current = base / 'current'
        staging = base / f'.current-stage-{uuid.uuid4().hex}'
        staging.mkdir(mode=0o750)
        try:
            for src in version_dir.iterdir():
                if src.is_file():
                    shutil.copy2(src, staging / src.name)
            self._fsync_tree(staging)
            self._atomic_exchange(current, staging)
            self._fsync_dir(base)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        # After exchange, staging contains the previous current tree.
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _atomic_exchange(a: Path, b: Path) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        if renameat2 is None:
            raise OSError(errno.ENOSYS, 'renameat2 is required for atomic current publication')
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        rc = renameat2(
            _AT_FDCWD, os.fsencode(str(a)),
            _AT_FDCWD, os.fsencode(str(b)),
            _RENAME_EXCHANGE,
        )
        if rc != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), f'{a} <-> {b}')

    @staticmethod
    def _fsync_tree(path: Path) -> None:
        for p in path.iterdir():
            if p.is_file():
                with p.open('rb') as fh:
                    os.fsync(fh.fileno())
        PlanStorage._fsync_dir(path)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def append_log(self, plan_id: str, event: dict[str, Any]) -> None:
        p = self.ensure(plan_id) / 'logs/processing.jsonl'
        row = {'ts': datetime.now(timezone.utc).isoformat(), **event}
        with p.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def write_json_atomic(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f'.tmp-{uuid.uuid4().hex}')
        with tmp.open('w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        PlanStorage._fsync_dir(path.parent)

    @staticmethod
    def sha256_json(data: Any) -> str:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(raw).hexdigest()
