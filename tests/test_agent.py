from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.agent import GeometryAgent
from backend.agent.validator import authoritative_snapshot, validate_candidate
from backend.config import Settings
from backend.db import Database
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage
from tests.test_geometry import process, wall


class FakeClient:
    def __init__(self, reply): self.reply = reply; self.calls = 0
    def propose(self, system_prompt, context): self.calls += 1; return self.reply


def test_candidate_gate_rejects_authoritative_length_mutation():
    n, _, s, _ = process({"planId": "guard", "walls": [
        wall("w1", (0,0), (200,0), 200), wall("w2", (200,0), (200,300), 300),
        wall("w3", (200,300), (0,300), 200), wall("w4", (0,300), (0,0), 300),
    ]})
    snapshot = authoritative_snapshot(n); candidate = copy.deepcopy(n); candidate.walls[0].length_mm = 1999
    topology = build_topology(candidate); solved = solve_geometry(candidate, topology)
    gate = validate_candidate(snapshot, candidate, topology, solved, 0.0, .5)
    assert gate.accepted is False and "declared lengths changed" in gate.reason


def test_agent_accepts_only_tools_never_coordinates_or_measurement_edits():
    n, t, s, _ = process({"planId": "agent", "walls": [
        wall("w1", (0,0), (100,20), 102), wall("w2", (100,20), (160,120), 117),
    ]})
    before = {w.id: w.length_mm for w in n.walls}
    client = FakeClient({"operations": [{
        "tool": "make_perpendicular", "args": {"wallA": "w1", "wallB": "w2"},
        "confidence": .99, "declaredLengthMm": 1, "x": 999999,
    }]})
    run = GeometryAgent(client, max_iterations=99).improve(n, t, s)
    assert run.iterations <= 5
    assert {w.id: w.length_mm for w in run.plan.walls} == before


def test_ollama_offline_does_not_break_deterministic_pipeline(tmp_path: Path):
    s = Settings("", tmp_path/"data", tmp_path/"data/db.sqlite3", "127.0.0.1", 9888,
                 120, 2700, 250, 25, .5, True, "http://127.0.0.1:9", "offline", .05)
    storage = PlanStorage(s.data_dir); pipe = Pipeline(s, storage, Database(s.db_path))
    p = PlanPayload.model_validate({"planId": "offline", "walls": [
        wall("w1", (0,0), (200,0), 200), wall("w2", (200,0), (200,300), 300),
        wall("w3", (200,300), (0,300), 200), wall("w4", (0,300), (0,0), 280),
    ]})
    pipe.save_raw(p); result = pipe.process("offline")
    assert result["status"] == "NEEDS_REVIEW" and result["aiAvailable"] is False
    current = storage.plan_dir("offline")/"current"
    assert (current/"plan.dxf").exists() and (current/"plan3d.json").exists()
    manifest = json.loads((current/"manifest.json").read_text())
    assert manifest["agent"]["offline"] is True and manifest["agent"]["aiAvailable"] is False
