from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend.storage import PlanStorage


def _write_version(storage: PlanStorage, plan_id: str, version: int, files: dict[str, str]) -> Path:
    out = storage.version_dir(plan_id, version)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return out


def test_publish_current_is_complete_and_replaces_as_one_snapshot(tmp_path: Path):
    storage = PlanStorage(tmp_path)
    v1 = _write_version(storage, "p1", 1, {"a.txt": "old-a", "b.txt": "old-b"})
    storage.publish_current("p1", v1)
    current = storage.plan_dir("p1") / "current"
    assert {p.name for p in current.iterdir()} == {"a.txt", "b.txt"}

    v2 = _write_version(storage, "p1", 2, {"a.txt": "new-a", "c.txt": "new-c"})
    storage.publish_current("p1", v2)
    assert {p.name for p in current.iterdir()} == {"a.txt", "c.txt"}
    assert (current / "a.txt").read_text() == "new-a"


def test_copy_failure_never_clears_existing_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = PlanStorage(tmp_path)
    v1 = _write_version(storage, "p2", 1, {"a.txt": "stable", "b.txt": "stable"})
    storage.publish_current("p2", v1)
    current = storage.plan_dir("p2") / "current"

    v2 = _write_version(storage, "p2", 2, {"a.txt": "new", "b.txt": "new"})
    real = shutil.copy2
    calls = {"n": 0}
    def fail_second(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return real(src, dst, *args, **kwargs)
    monkeypatch.setattr(shutil, "copy2", fail_second)

    with pytest.raises(OSError):
        storage.publish_current("p2", v2)

    assert (current / "a.txt").read_text() == "stable"
    assert (current / "b.txt").read_text() == "stable"
