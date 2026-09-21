from __future__ import annotations

import json
from pathlib import Path

from backend.agent.ollama import OllamaClient
from backend.config import Settings
from backend.db import Database
from backend.models import PlanPayload
from backend.pipeline import Pipeline
from backend.storage import PlanStorage
from tests.test_geometry import wall


def _pipeline(tmp_path: Path, ai: bool) -> tuple[Pipeline, PlanStorage]:
    s = Settings("", tmp_path / "data", tmp_path / "data/db.sqlite3", "127.0.0.1", 9888,
                 120, 2700, 250, 25, .5, ai, "http://127.0.0.1:9", "fake", .05)
    storage = PlanStorage(s.data_dir)
    return Pipeline(s, storage, Database(s.db_path)), storage


ROOM = [wall("w1", (0, 0), (200, 0), 200), wall("w2", (200, 0), (200, 250), 250),
        wall("w3", (200, 250), (0, 250), 200), wall("w4", (0, 250), (0, 0), 250)]


def test_ia_nomina_la_stanza_e_il_computo_si_aggiorna(tmp_path, monkeypatch):
    replies = []

    def fake_propose(self, system_prompt, context):
        replies.append(context)
        return {
            "rooms": [{"roomId": "room-1", "name": "Bagno", "type": "bagno"},
                      {"roomId": "inesistente", "name": "X", "type": "cucina"}],
            "questions": ["La finestra è sopra la vasca?"],
            "summary": "Bagno rettangolare 2,00 x 2,50 m.",
            "x": 999,
        }

    monkeypatch.setattr(OllamaClient, "propose", fake_propose)
    pipe, storage = _pipeline(tmp_path, ai=True)
    pipe.save_raw(PlanPayload.model_validate({"planId": "ai", "walls": ROOM, "notes": ["piastrelle da rifare"]}))
    result = pipe.process("ai")
    assert result["status"] == "PROCESSED"
    assert replies and "coordinates" not in json.dumps(replies[0])
    processed = json.loads((storage.plan_dir("ai") / "current" / "processed-plan.json").read_text())
    room = processed["rooms"][0]
    assert room["name"] == "Bagno" and room["type"] == "bagno"
    assert room["tilingAreaM2"] > 0  # il tipo proposto dall'IA attiva il rivestimento
    assert room["floorAreaM2"] == 5.0  # la geometria non cambia
    totals = result["totals"]
    assert totals["aiSummary"].startswith("Bagno")
    assert "La finestra è sopra la vasca?" in totals["questions"]


def test_nome_dato_dall_utente_non_viene_sovrascritto(tmp_path, monkeypatch):
    monkeypatch.setattr(OllamaClient, "propose",
                        lambda self, p, c: {"rooms": [{"roomId": "r1", "name": "Cucina", "type": "cucina"}]})
    pipe, storage = _pipeline(tmp_path, ai=True)
    pipe.save_raw(PlanPayload.model_validate({
        "planId": "user", "walls": ROOM,
        "rooms": [{"id": "r1", "name": "Studio", "wallIds": ["w1", "w2", "w3", "w4"]}],
    }))
    pipe.process("user")
    room = json.loads((storage.plan_dir("user") / "current" / "processed-plan.json").read_text())["rooms"][0]
    assert room["name"] == "Studio" and room["type"] == "studio"


def test_totali_senza_ia(tmp_path):
    pipe, _ = _pipeline(tmp_path, ai=False)
    pipe.save_raw(PlanPayload.model_validate({"planId": "tot", "walls": ROOM}))
    totals = pipe.process("tot")["totals"]
    assert totals["floorAreaM2"] == 5.0 and totals["ceilingAreaM2"] == 5.0
    assert totals["grossWallAreaM2"] == 24.3 and totals["volumeM3"] == 13.5
    assert totals["aiSummary"] is None
