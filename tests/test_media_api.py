from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _payload():
    return {
        "version": 4,
        "planId": "photo-plan",
        "name": "Foto cantiere",
        "walls": [
            {"id": "w1", "a": {"x": 0, "y": 0}, "b": {"x": 200, "y": 0}, "lengthCm": 200},
        ],
    }


def test_photo_upload_list_download_delete(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GE360_API_KEY", "photo-key")
    monkeypatch.setenv("GE360_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GE360_DB_PATH", str(tmp_path / "data" / "db.sqlite3"))
    monkeypatch.setenv("GE360_AI_ENABLED", "false")
    import backend.main as main
    main = importlib.reload(main)
    client = TestClient(main.app)
    h = {"X-GE360-API-Key": "photo-key"}
    assert client.post("/api/v1/plans", json=_payload(), headers=h).status_code == 200

    tiny_png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    up = client.post(
        "/api/v1/plans/photo-plan/photos",
        headers=h,
        data={"targetType": "wall", "targetId": "w1", "caption": "Misura laser parete"},
        files={"file": ("parete.png", tiny_png, "image/png")},
    )
    assert up.status_code == 200, up.text
    photo = up.json()["photo"]
    assert photo["targetType"] == "wall" and photo["targetId"] == "w1"

    listing = client.get("/api/v1/plans/photo-plan/photos", headers=h).json()
    assert len(listing["photos"]) == 1
    got = client.get(photo["url"], headers=h)
    assert got.status_code == 200 and got.content == tiny_png
    assert client.delete(f"/api/v1/plans/photo-plan/photos/{photo['id']}", headers=h).status_code == 200
    assert client.get("/api/v1/plans/photo-plan/photos", headers=h).json()["photos"] == []
