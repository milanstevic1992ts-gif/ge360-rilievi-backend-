from __future__ import annotations

from pathlib import Path

from backend.cad import build_cad_model, export_pdf
from backend.cad.pdf_exporter import _opening_type_label, _wall_construction_style
from backend.geometry.normalizer import normalize_payload
from backend.geometry.solver import solve_geometry
from backend.geometry.topology import build_topology
from backend.models import PlanPayload


def _wall(wid, a, b, length, **extra):
    return {
        "id": wid,
        "a": {"x": a[0], "y": a[1]},
        "b": {"x": b[0], "y": b[1]},
        "lengthCm": length,
        **extra,
    }


def _model():
    payload = PlanPayload.model_validate(
        {
            "planId": "technical-pdf",
            "name": "Pianta tecnica",
            "wallHeightM": 2.8,
            "walls": [
                _wall("w1", (0, 0), (300, 0), 300, constructionState="demolish", constructionThicknessCm=10, thicknessMm=100),
                _wall("w2", (300, 0), (300, 400), 400, constructionState="new", constructionThicknessCm=12, thicknessMm=120),
                _wall("w3", (300, 400), (0, 400), 300),
                _wall("w4", (0, 400), (0, 0), 400),
            ],
            "rooms": [
                {"id": "room-1", "name": "Soggiorno", "wallIds": ["w1", "w2", "w3", "w4"]}
            ],
            "openings": [
                {
                    "id": "door-armored",
                    "type": "door",
                    "wallId": "w2",
                    "widthCm": 90,
                    "heightCm": 210,
                    "offsetCm": 80,
                    "referenceEnd": "a",
                    "doorKind": "armored",
                    "category": "armored",
                    "leaves": 1,
                    "armored": True,
                    "hingeEnd": "a",
                    "swingDirection": "inward",
                    "swingSide": 1,
                },
                {
                    "id": "window-triple",
                    "type": "window",
                    "wallId": "w4",
                    "widthCm": 180,
                    "heightCm": 120,
                    "sillHeightCm": 90,
                    "offsetCm": 80,
                    "referenceEnd": "a",
                    "windowKind": "triple",
                    "leaves": 3,
                },
            ],
        }
    )
    normalized = normalize_payload(payload)
    topology = build_topology(normalized)
    solved = solve_geometry(normalized, topology)
    return build_cad_model(normalized, solved)


def test_technical_metadata_survives_to_cad_model():
    model = _model()
    walls = {wall.id: wall for wall in model.walls}
    openings = {opening.id: opening for opening in model.openings}

    assert walls["w1"].constructionState == "demolish"
    assert walls["w1"].constructionThicknessMm == 100
    assert walls["w2"].constructionState == "new"
    assert walls["w2"].constructionThicknessMm == 120
    assert walls["w3"].constructionState == "existing"

    door = openings["door-armored"]
    assert door.doorKind == "armored"
    assert door.armored is True
    assert door.hingeEnd == "a"
    assert door.swingDirection == "inward"
    assert door.swingSide == 1
    assert _opening_type_label(door) == "Porta blindata"

    window = openings["window-triple"]
    assert window.windowKind == "triple"
    assert window.leaves == 3
    assert _opening_type_label(window) == "Finestra tripla"

    assert _wall_construction_style(walls["w1"])[2] == "DEMOLIRE"
    assert _wall_construction_style(walls["w2"])[2] == "NUOVO"


def test_pdf_contains_technical_plan_labels(tmp_path: Path):
    model = _model()
    path = tmp_path / "technical-plan.pdf"
    export_pdf(model, path)

    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert path.stat().st_size > 1000
    # pageCompression=0: these labels are deliberately inspectable in the generated report.
    assert b"DEMOLIRE" in data
    assert b"NUOVO" in data
    assert b"Porta blindata" in data
    assert b"Finestra tripla" in data
    assert b"Planimetria generale" in data
