from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient


FIXTURE = Path(__file__).parent / "fixtures" / "openplan3d-v4.json"


def _wait(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(300):
        state = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if state["status"] in {"DONE", "ERROR"}:
            return state
        time.sleep(0.02)
    raise AssertionError("frontend v4 job timeout")


def test_real_openplan3d_v4_payload_roundtrip(tmp_path: Path, monkeypatch):
    """Locks the backend to the planPayload() contract used by ge360-open-plan3d/js/app.js."""
    monkeypatch.setenv("GE360_API_KEY", "frontend-contract-key")
    monkeypatch.setenv("GE360_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GE360_DB_PATH", str(tmp_path / "data" / "db.sqlite3"))
    monkeypatch.setenv("GE360_AI_ENABLED", "false")

    import backend.main as main

    main = importlib.reload(main)
    client = TestClient(main.app)
    headers = {"X-GE360-API-Key": "frontend-contract-key"}
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["works"] = [
        {"id":"work-paint","catalogId":"paint.walls_ceiling","targetType":"plan"},
        {"id":"work-floor","catalogId":"tiles.install.floor","targetType":"room","targetId":"room-1"},
    ]

    queued = client.post("/api/v1/plans/refine", json=payload, headers=headers)
    assert queued.status_code == 200
    queued_body = queued.json()
    assert queued_body["success"] is True
    assert queued_body["planId"] == payload["planId"]
    assert queued_body["status"] in {"QUEUED", "PROCESSING"}

    done = _wait(client, queued_body["jobId"], headers)
    assert done["status"] == "DONE", done

    status = client.get(f"/api/v1/plans/{payload['planId']}", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "PROCESSED"
    assert body["technicalSchema"] == "ge360-technical-plan-v1"
    assert body["summary"] == {"rooms": 1, "floorAreaM2": 6.0}
    assert body["files"]["glb"] is None

    for artifact in ("processed", "preview", "png", "svg", "pdf", "dxf", "3d"):
        response = client.get(
            f"/api/v1/plans/{payload['planId']}/{artifact}",
            headers=headers,
        )
        assert response.status_code == 200, artifact

    processed = client.get(
        f"/api/v1/plans/{payload['planId']}/processed",
        headers=headers,
    ).json()
    assert processed["technicalSchema"] == "ge360-technical-plan-v1"
    assert processed["metadata"]["technicalSchema"] == "ge360-technical-plan-v1"
    lengths = {wall["id"]: wall["declaredLengthMm"] for wall in processed["walls"]}
    assert lengths == {"w1": 2000.0, "w2": 3000.0, "w3": 2000.0, "w4": 3000.0}

    door = next(item for item in processed["openings"] if item["id"] == "door-1")
    assert door["widthMm"] == 800.0
    assert door["offsetMm"] == 1000.0
    assert door["referenceEnd"] == "a"

    original = json.loads(
        (tmp_path / "data" / payload["planId"] / "raw" / "original.json").read_text(encoding="utf-8")
    )
    assert original["version"] == 4
    assert original["kind"] == "ge360-rough-survey"
    assert original["rawStrokes"] == payload["rawStrokes"]
    assert original["rooms"] == payload["rooms"]
    assert original["notes"] == payload["notes"]
    assert [w["id"] for w in original["works"]] == [w["id"] for w in payload["works"]]
    assert [w["catalogId"] for w in original["works"]] == [w["catalogId"] for w in payload["works"]]
    assert original["works"][1]["targetId"] == "room-1"
    assert original["surfaces"] == payload["surfaces"]

    works = processed["metadata"]["works"]
    assert len(works) == 2
    assert works[0]["quantitySource"] == "authoritative-plan-geometry"
    assert works[0]["quantity"] > 6.0
    assert works[1]["quantity"] == 6.0

    catalog = client.get("/api/v1/work-catalog", headers=headers)
    assert catalog.status_code == 200
    assert any(row["id"] == "paint.walls" for row in catalog.json()["works"])
