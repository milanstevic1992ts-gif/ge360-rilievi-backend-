from __future__ import annotations

import json
from pathlib import Path

from backend.archive import PlanDocumentArchive
from backend.storage import PlanStorage


class FakeDB:
    def __init__(self, plan_id: str, name: str):
        self.plan_id = plan_id
        self.name = name
        self.media = []

    def get(self, plan_id: str):
        if plan_id != self.plan_id:
            return None
        return {
            "plan_id": plan_id,
            "name": self.name,
            "created_at": "2026-09-22T10:00:00+00:00",
            "updated_at": "2026-09-22T12:00:00+00:00",
            "status": "PROCESSED",
            "current_version": 2,
        }

    def list_plans(self, limit=1000):
        return [self.get(self.plan_id)]

    def list_media(self, plan_id: str):
        return list(self.media)


def test_local_documents_archive_contains_complete_survey(tmp_path: Path):
    plan_id = "rilievo-001"
    storage = PlanStorage(tmp_path / "data")
    db = FakeDB(plan_id, "Casa Rossi")
    archive = PlanDocumentArchive(tmp_path / "Documenti" / "Rilievi", storage, db)

    original = {
        "planId": plan_id,
        "name": "Casa Rossi",
        "walls": [{"id": "w1"}],
        "openings": [],
        "rooms": [],
        "notes": [{"id": "n1", "targetLabel": "Cucina", "text": "Demolire pavimento"}],
        "works": [{"id": "wk1", "label": "Demolizione pavimento"}],
    }
    storage.save_raw(plan_id, original)
    latest = {**original, "walls": [{"id": "w1"}, {"id": "w2"}], "notes": original["notes"] + [{"id":"n2","text":"Controsoffitto"}]}
    storage.save_raw(plan_id, latest)

    for version in (1, 2):
        out = storage.version_dir(plan_id, version)
        (out / "plan.pdf").write_bytes(b"%PDF-1.4\n" + bytes([version]))
        (out / "preview.png").write_bytes(b"PNG" + bytes([version]))
        (out / "manifest.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    storage.publish_current(plan_id, storage.version_dir(plan_id, 2))

    photo = storage.media_dir(plan_id) / "photo1.jpg"
    photo.write_bytes(b"jpeg")
    db.media.append({
        "media_id": "media001",
        "plan_id": plan_id,
        "filename": "doccia.jpg",
        "path": str(photo),
        "created_at": "2026-09-22T11:00:00+00:00",
    })

    archive.record_event(plan_id, "RILIEVO AGGIORNATO", archive.summarize_raw_change(original, latest))
    manifest = archive.sync_plan(plan_id)
    folder = Path(manifest["localArchive"])

    assert folder.name.startswith("2026-09-22__Casa Rossi__")
    assert (folder / "Schizzo_originale.json").is_file()
    assert (folder / "Schizzo_ultimo.json").is_file()
    assert (folder / "Schizzi" / "original.json").is_file()
    assert len(list((folder / "Schizzi").glob("received-*.json"))) == 1
    assert "Demolire pavimento" in (folder / "Appunti.md").read_text(encoding="utf-8")
    assert json.loads((folder / "Lavorazioni.json").read_text(encoding="utf-8"))[0]["id"] == "wk1"
    assert (folder / "PDF" / "Rilievo_V001.pdf").is_file()
    assert (folder / "PDF" / "Rilievo_V002.pdf").is_file()
    assert (folder / "PDF" / "ULTIMO.pdf").is_file()
    assert (folder / "Versioni" / "V001" / "preview.png").is_file()
    assert len(list((folder / "Foto").glob("*doccia.jpg"))) == 1

    log = (folder / "LOG.txt").read_text(encoding="utf-8")
    assert "RILIEVO AGGIORNATO" in log
    assert "muri 1→2" in log
    assert "appunti 1→2" in log

    saved_manifest = json.loads((folder / "Manifest.json").read_text(encoding="utf-8"))
    assert saved_manifest["counts"]["pdf"] == 2
    assert saved_manifest["counts"]["versions"] == 2
    assert saved_manifest["counts"]["photos"] == 1
    assert saved_manifest["counts"]["notes"] == 2


def test_archive_keeps_deleted_photo_copy_as_backup(tmp_path: Path):
    plan_id = "rilievo-photo"
    storage = PlanStorage(tmp_path / "data")
    db = FakeDB(plan_id, "Bagno")
    archive = PlanDocumentArchive(tmp_path / "Documenti" / "Rilievi", storage, db)
    storage.save_raw(plan_id, {"planId": plan_id, "name": "Bagno", "notes": [], "works": []})

    src = storage.media_dir(plan_id) / "x.jpg"
    src.write_bytes(b"foto")
    db.media = [{"media_id":"m1","filename":"prima.jpg","path":str(src),"created_at":"2026-09-22T11:00:00Z"}]
    folder = Path(archive.sync_plan(plan_id)["localArchive"])
    copied = list((folder / "Foto").glob("*prima.jpg"))
    assert len(copied) == 1

    db.media = []
    src.unlink()
    archive.record_event(plan_id, "FOTO ELIMINATA", "prima.jpg")
    archive.sync_plan(plan_id)
    assert copied[0].is_file(), "l'archivio locale deve conservare la copia storica"
