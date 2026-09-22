from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_backup_script_keeps_only_ten(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    db = tmp_path / "ge360.sqlite3"
    con = sqlite3.connect(db)
    con.execute("create table test(value text)")
    con.execute("insert into test values ('ok')")
    con.commit()
    con.close()

    backup_dir.mkdir()
    old_names = set()
    for day in range(1, 13):
        p = backup_dir / f"ge360-config-2026-08-{day:02d}.tar.gz"
        p.write_bytes(b"old")
        os.utime(p, (day, day))
        old_names.add(p.name)

    env = os.environ.copy()
    env.update({
        "GE360_CONFIG_BACKUP_DIR": str(backup_dir),
        "GE360_CONFIG_BACKUP_KEEP": "10",
        "GE360_DB_PATH": str(db),
    })
    subprocess.run(["bash", str(ROOT / "scripts" / "ge360-config-backup.sh")], check=True, env=env)

    backups = sorted(backup_dir.glob("ge360-config-*.tar.gz"))
    assert len(backups) == 10
    assert any(p.name not in old_names for p in backups)

    newest = max(backups, key=lambda p: p.stat().st_mtime)
    listing = subprocess.check_output(["tar", "-tzf", str(newest)], text=True)
    assert "MANIFEST.txt" in listing
    assert str(db).lstrip("/") in listing


def test_backup_timer_is_daily_persistent_and_restore_exists():
    timer = (ROOT / "packaging" / "deb" / "ge360-config-backup.timer").read_text(encoding="utf-8")
    service = (ROOT / "packaging" / "deb" / "ge360-config-backup.service").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "ge360-config-restore.sh").read_text(encoding="utf-8")
    backup = (ROOT / "scripts" / "ge360-config-backup.sh").read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 03:15:00" in timer
    assert "Persistent=true" in timer
    assert "ge360-config-backup" in service
    assert 'if [[ "${KEEP:-10}" -lt 10 ]]; then KEEP=10; fi' in backup
    assert "ge360-config-restore latest" in backup
    assert "systemctl restart ge360-rilievi-backend.service" in restore
