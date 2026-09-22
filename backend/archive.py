from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.db import Database
from backend.storage import PlanStorage


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str, fallback: str = "Rilievo") -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", " ", str(value or "")).strip()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" .-_")
    return (value or fallback)[:80]


def _safe_file(value: str, fallback: str = "file") -> str:
    return _slug(value, fallback).replace(" ", "_")


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class PlanDocumentArchive:
    """Human-readable local mirror of every persisted GE360 survey."""

    def __init__(self, root: Path, storage: PlanStorage, db: Database):
        self.root = Path(root)
        self.storage = storage
        self.db = db
        self.root.mkdir(parents=True, exist_ok=True)

    def _row(self, plan_id: str) -> dict:
        return self.db.get(plan_id) or {}

    def _latest_raw(self, plan_id: str) -> dict:
        try:
            return self.storage.raw_payload(plan_id)
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def folder_for(self, plan_id: str) -> Path:
        row = self._row(plan_id)
        raw = self._latest_raw(plan_id)
        created = str(row.get("created_at") or row.get("createdAt") or _utcnow())
        date = created[:10] if len(created) >= 10 else datetime.now(timezone.utc).date().isoformat()
        name = _slug(row.get("name") or raw.get("name") or plan_id)
        suffix = f"__{plan_id}"

        existing = next((p for p in self.root.iterdir() if p.is_dir() and p.name.endswith(suffix)), None)
        desired = self.root / f"{date}__{name}{suffix}"
        if existing is not None:
            if existing != desired and not desired.exists():
                try:
                    existing.rename(desired)
                    existing = desired
                except OSError:
                    pass
            return existing
        desired.mkdir(parents=True, exist_ok=True)
        return desired

    @staticmethod
    def _copy_if_changed(src: Path, dst: Path) -> bool:
        if not src.is_file():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            try:
                if src.stat().st_size == dst.stat().st_size and int(src.stat().st_mtime) <= int(dst.stat().st_mtime):
                    return False
            except OSError:
                pass
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copy2(src, tmp)
        tmp.replace(dst)
        return True

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _notes_markdown(raw: dict) -> str:
        notes = raw.get("notes") or []
        lines = ["# Appunti GE360", ""]
        if not notes:
            lines += ["Nessun appunto salvato.", ""]
            return "\n".join(lines)

        for index, note in enumerate(notes, 1):
            if not isinstance(note, dict):
                lines += [f"## Appunto {index}", "", str(note), ""]
                continue
            title = note.get("targetLabel") or note.get("roomName") or note.get("targetType") or f"Appunto {index}"
            text = (
                note.get("cleanedText")
                or note.get("text")
                or note.get("rawText")
                or note.get("note")
                or note.get("body")
                or ""
            )
            lines += [f"## {title}", ""]
            meta = []
            if note.get("createdAt"):
                meta.append(f"Data: {note['createdAt']}")
            if note.get("targetType"):
                meta.append(f"Tipo: {note['targetType']}")
            if note.get("targetId"):
                meta.append(f"Elemento: {note['targetId']}")
            if meta:
                lines += [" · ".join(meta), ""]
            lines += [str(text).strip() or "_Appunto senza testo_", ""]
            tasks = note.get("tasks") or []
            if tasks:
                lines += ["Attività:"]
                lines += [f"- {task}" for task in tasks]
                lines += [""]
        return "\n".join(lines)

    def record_event(self, plan_id: str, event: str, detail: str = "") -> None:
        folder = self.folder_for(plan_id)
        line = f"[{_utcnow()}] {event}"
        if detail:
            line += f" — {detail.strip()}"
        line += "\n"
        log = folder / "LOG.txt"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()

        structured = folder / "LOG.jsonl"
        with structured.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _utcnow(), "event": event, "detail": detail}, ensure_ascii=False) + "\n")
            fh.flush()

    @staticmethod
    def summarize_raw_change(previous: dict | None, current: dict) -> str:
        if not previous:
            return "rilievo creato"
        labels = {
            "walls": "muri",
            "openings": "porte/finestre",
            "rooms": "stanze",
            "diagonals": "diagonali",
            "notes": "appunti",
            "works": "lavorazioni",
        }
        changed = []
        for key, label in labels.items():
            before = previous.get(key) or []
            after = current.get(key) or []
            if _digest(before) != _digest(after):
                changed.append(f"{label} {len(before)}→{len(after)}" if len(before) != len(after) else f"{label} modificati")
        if not changed and _digest(previous) != _digest(current):
            changed.append("dati generali modificati")
        return ", ".join(changed) if changed else "nessuna differenza dati"

    def sync_plan(self, plan_id: str) -> dict:
        folder = self.folder_for(plan_id)
        source = self.storage.plan_dir(plan_id)
        raw_dir = source / "raw"
        latest = self._latest_raw(plan_id)

        sketches = folder / "Schizzi"
        sketches.mkdir(parents=True, exist_ok=True)
        if raw_dir.is_dir():
            for item in sorted(raw_dir.glob("*.json")):
                self._copy_if_changed(item, sketches / item.name)

        self._copy_if_changed(raw_dir / "original.json", folder / "Schizzo_originale.json")
        self._copy_if_changed(raw_dir / "latest.json", folder / "Schizzo_ultimo.json")

        (folder / "Appunti.md").write_text(self._notes_markdown(latest), encoding="utf-8")
        self._write_json(folder / "Lavorazioni.json", latest.get("works") or [])

        pdf_dir = folder / "PDF"
        versions_dir = folder / "Versioni"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        versions_dir.mkdir(parents=True, exist_ok=True)
        versions = source / "versions"
        version_count = 0
        pdf_count = 0
        if versions.is_dir():
            for version in sorted(p for p in versions.iterdir() if p.is_dir() and p.name.isdigit()):
                version_count += 1
                vno = int(version.name)
                target_version = versions_dir / f"V{vno:03d}"
                target_version.mkdir(parents=True, exist_ok=True)
                for item in version.iterdir():
                    if item.is_file():
                        self._copy_if_changed(item, target_version / item.name)
                pdf = version / "plan.pdf"
                if pdf.is_file():
                    self._copy_if_changed(pdf, pdf_dir / f"Rilievo_V{vno:03d}.pdf")
                    pdf_count += 1

        current_pdf = source / "current" / "plan.pdf"
        if current_pdf.is_file():
            self._copy_if_changed(current_pdf, pdf_dir / "ULTIMO.pdf")

        photos_dir = folder / "Foto"
        photos_dir.mkdir(parents=True, exist_ok=True)
        media = self.db.list_media(plan_id)
        for row in media:
            src = Path(row.get("path") or "")
            if not src.is_file():
                continue
            stamp = str(row.get("created_at") or "")[:10].replace("-", "")
            filename = _safe_file(row.get("filename") or src.name, src.stem) + src.suffix.lower()
            target = photos_dir / f"{stamp or 'foto'}__{str(row.get('media_id') or '')[:8]}__{filename}"
            self._copy_if_changed(src, target)

        processing_log = source / "logs" / "processing.jsonl"
        self._copy_if_changed(processing_log, folder / "Log_tecnico.jsonl")

        row = self._row(plan_id)
        manifest = {
            "planId": plan_id,
            "name": row.get("name") or latest.get("name") or plan_id,
            "createdAt": row.get("created_at") or row.get("createdAt"),
            "updatedAt": row.get("updated_at") or row.get("updatedAt"),
            "status": row.get("status"),
            "currentVersion": row.get("current_version") or row.get("currentVersion") or 0,
            "localArchive": str(folder),
            "lastSyncedAt": _utcnow(),
            "counts": {
                "pdf": pdf_count,
                "versions": version_count,
                "photos": len(media),
                "notes": len(latest.get("notes") or []),
                "works": len(latest.get("works") or []),
            },
        }
        self._write_json(folder / "Manifest.json", manifest)
        if not (folder / "LOG.txt").exists():
            self.record_event(plan_id, "ARCHIVIO CREATO", "cartella Documenti inizializzata")
        return manifest

    def sync_all(self, limit: int = 1000) -> list[dict]:
        rows = self.db.list_plans(limit)
        result = []
        for row in rows:
            try:
                result.append(self.sync_plan(row["plan_id"]))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                result.append({"planId": row["plan_id"], "error": str(exc)})
        return result

    def list_archives(self, sync: bool = False) -> list[dict]:
        if sync:
            self.sync_all()
        rows = []
        for row in self.db.list_plans(1000):
            plan_id = row["plan_id"]
            try:
                folder = self.folder_for(plan_id)
                manifest_path = folder / "Manifest.json"
                if manifest_path.is_file():
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                else:
                    data = self.sync_plan(plan_id)
                log = folder / "LOG.txt"
                tail = []
                if log.is_file():
                    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
                data["logTail"] = tail
                rows.append(data)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                rows.append({"planId": plan_id, "name": row.get("name"), "error": str(exc)})
        return rows
