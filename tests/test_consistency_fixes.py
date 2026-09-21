from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.agent.tools import apply_topology_operation
from backend.bridge.manager import DirectBridgeManager
from backend.bridge.store import BridgeStore
from backend.cad.model import build_cad_model
from backend.db import Database
from backend.geometry.normalizer import normalize_payload
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.models import PlanPayload
from backend.view3d import to_plan3d
from tests.test_device_pairing import FakeWireGuard as PairingWireGuard, endpoint as pairing_endpoint, settings as bridge_settings


def wall(i, a, b, cm=None):
    row = {"id": i, "a": {"x": a[0], "y": a[1]}, "b": {"x": b[0], "y": b[1]}}
    if cm is not None:
        row["lengthCm"] = cm
    return row


def test_database_migrates_legacy_jobs_for_revision_snapshots(tmp_path: Path):
    path = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE plans (
      plan_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL, status TEXT NOT NULL, current_version INTEGER NOT NULL DEFAULT 0,
      path TEXT NOT NULL, quality_json TEXT, needs_review INTEGER NOT NULL DEFAULT 0, last_error TEXT
    );
    CREATE TABLE jobs (
      job_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      result_json TEXT, error TEXT
    );
    CREATE UNIQUE INDEX idx_jobs_one_active_plan ON jobs(plan_id)
      WHERE status IN ('QUEUED','PROCESSING');
    """)
    con.close()

    Database(path)
    con = sqlite3.connect(path)
    columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
    indexes = {row[1] for row in con.execute("PRAGMA index_list(jobs)")}
    con.close()
    assert {"input_hash", "raw_json"} <= columns
    assert "idx_jobs_one_active_plan" not in indexes
    assert {"idx_jobs_one_processing_plan", "idx_jobs_hash"} <= indexes


def test_opening_from_reference_b_uses_solved_wall_length():
    payload = PlanPayload.model_validate({
        "planId": "opening-calculated",
        "walls": [
            wall("w1", (0, 0), (400, 0), 400),
            wall("w2", (400, 0), (400, 300), 300),
            wall("w3", (400, 300), (0, 520), 400),
            wall("w4", (0, 520), (0, 0)),
        ],
        "openings": [{
            "id": "d1", "type": "door", "wallId": "w4",
            "widthCm": 80, "offsetCm": 50, "referenceEnd": "b",
        }],
    })
    n = normalize_payload(payload)
    solved = solve_geometry(n, build_topology(n))
    model = build_cad_model(n, solved)
    w4 = next(w for w in model.walls if w.id == "w4")
    door = model.openings[0]
    assert w4.lengthSource == "CALCULATED"
    assert w4.calculatedLengthMm == pytest.approx(3000, abs=2)
    assert door.centerFromStartMm == pytest.approx(w4.calculatedLengthMm - 500 - 400, abs=2)


def test_suspect_measure_is_explicit_and_3d_uses_solved_length():
    payload = PlanPayload.model_validate({
        "planId": "suspect",
        "walls": [
            wall("top", (0, 0), (900, 0), 900),
            wall("right", (900, 0), (900, 300), 300),
            wall("bottom", (900, 300), (0, 300), 900),
            wall("left", (0, 300), (0, 0), 300),
            wall("s1", (300, 0), (300, 300), 330),
            wall("s2", (600, 0), (600, 300), 300),
        ],
    })
    n = normalize_payload(payload)
    solved = solve_geometry(n, build_topology(n))
    model = build_cad_model(n, solved)
    s1 = next(w for w in model.walls if w.id == "s1")
    assert s1.suspect is True
    assert s1.lengthSource == "SUSPECT_MEASURED"
    assert s1.declaredLengthMm == 3300
    assert s1.calculatedLengthMm == pytest.approx(3000, abs=15)
    p3 = to_plan3d(model)
    p3s1 = next(w for w in p3["walls"] if w["id"] == "s1")
    assert p3s1["length"] == pytest.approx(s1.calculatedLengthMm)
    assert p3s1["declaredLength"] == 3300


def test_agent_merge_nodes_updates_dependent_node_references():
    payload = PlanPayload.model_validate({
        "planId": "merge-refs",
        "walls": [
            wall("w1", (0, 0), (200, 0), 200),
            wall("w2", (200, 0), (200, 300), 300),
            wall("w3", (200, 300), (0, 300), 200),
            wall("w4", (0, 300), (0, 0), 300),
        ],
    })
    n = normalize_payload(payload)
    node_ids = list(n.nodes)
    keep, drop = node_ids[0], node_ids[2]
    n.diagonals = [{"id": "d", "nodeA": drop, "nodeB": node_ids[1], "lengthMm": 1000.0}]
    n.tees = [{"node": drop, "wallId": "w1", "t": 0.5}]
    candidate, reason = apply_topology_operation(
        {"tool": "merge_nodes", "args": {"nodeA": keep, "nodeB": drop}, "confidence": 0.99},
        n,
        max_gap_mm=10000,
    )
    assert reason == "ok" and candidate is not None
    assert drop not in candidate.nodes
    assert all(d["nodeA"] in candidate.nodes and d["nodeB"] in candidate.nodes for d in candidate.diagonals)
    assert all(t["node"] in candidate.nodes for t in candidate.tees)


def test_duplicate_entity_ids_and_nonfinite_coordinates_are_rejected():
    with pytest.raises(ValidationError):
        PlanPayload.model_validate({
            "planId": "dup",
            "walls": [
                wall("w1", (0, 0), (100, 0), 100),
                wall("w1", (100, 0), (100, 100), 100),
            ],
        })
    with pytest.raises(ValidationError):
        PlanPayload.model_validate({
            "planId": "inf",
            "walls": [wall("w1", (0, 0), (float("inf"), 0), 100)],
        })


def test_pairing_failure_after_token_issue_rolls_back_device(tmp_path: Path, monkeypatch):
    from backend.bridge import manager as manager_module

    s = bridge_settings(tmp_path)
    store = BridgeStore(s.db_path)
    wg = PairingWireGuard()
    manager = DirectBridgeManager(s, store=store, wireguard=wg)
    monkeypatch.setattr(manager_module, "resolve_public_endpoint", lambda _s: pairing_endpoint())
    monkeypatch.setattr(manager_module, "try_upnp_mapping", lambda _s: {"enabled": False, "attempted": False, "mapped": False, "error": None})

    def fail_server_key():
        raise RuntimeError("server key unavailable")

    wg.server_public_key = fail_server_key
    with pytest.raises(RuntimeError, match="server key unavailable"):
        manager.create_device("Telefono")
    assert store.list(active_only=True) == []
    assert wg.removed == ["phone-public"]
