from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models import PlanPayload


def _base(**extra):
    payload = {
        "planId": "technical-contract",
        "name": "Contratto tecnico",
        "walls": [
            {
                "id": "w1",
                "a": {"x": 0, "y": 0},
                "b": {"x": 100, "y": 0},
                "lengthCm": 300,
            }
        ],
        "openings": [],
        "rooms": [],
        "diagonals": [],
    }
    payload.update(extra)
    return payload


def test_technical_schema_defaults_for_legacy_payload():
    payload = PlanPayload.model_validate(_base())
    assert payload.version == 4
    assert payload.technicalSchema == "ge360-technical-plan-v1"
    assert payload.walls[0].constructionState == "existing"
    assert payload.walls[0].constructionThicknessCm is None


def test_legacy_openings_are_normalized_without_breaking_clients():
    raw = _base(
        openings=[
            {
                "id": "d1",
                "type": "door",
                "wallId": "w1",
                "widthCm": 80,
                "offsetCm": 20,
            },
            {
                "id": "f1",
                "type": "window",
                "wallId": "w1",
                "widthCm": 100,
                "offsetCm": 120,
            },
        ]
    )
    payload = PlanPayload.model_validate(raw)
    door, window = payload.openings

    assert door.doorKind == "internal"
    assert door.leaves == 1
    assert door.armored is False
    assert door.sliding is False
    assert door.hingeEnd == "a"
    assert door.swingDirection == "inward"
    assert door.swingSide == 1

    assert window.windowKind == "single"
    assert window.leaves == 1
    assert window.armored is False
    assert window.sliding is False


def test_technical_openings_are_canonicalized():
    raw = _base(
        openings=[
            {
                "id": "d1",
                "type": "door",
                "wallId": "w1",
                "widthCm": 140,
                "offsetCm": 20,
                "doorKind": "armored-double",
                "leaves": 1,
                "armored": False,
                "swingDirection": "outward",
                "swingSide": -1,
            },
            {
                "id": "f1",
                "type": "window",
                "wallId": "w1",
                "widthCm": 140,
                "offsetCm": 120,
                "windowKind": "balcony-double",
                "sillHeightCm": 90,
                "leaves": 1,
            },
        ]
    )
    payload = PlanPayload.model_validate(raw)
    door, window = payload.openings

    assert door.doorKind == "armored-double"
    assert door.armored is True
    assert door.category == "armored"
    assert door.leaves == 2
    assert door.swingDirection == "outward"
    assert door.swingSide == -1

    assert window.windowKind == "balcony-double"
    assert window.balconyDoor is True
    assert window.leaves == 2
    assert window.sillHeightCm == 0.0
    assert window.sillHeightMm == 0.0


@pytest.mark.parametrize("state", ["new", "demolish"])
def test_new_or_demolished_wall_requires_real_thickness(state):
    raw = _base(
        walls=[
            {
                "id": "w1",
                "a": {"x": 0, "y": 0},
                "b": {"x": 100, "y": 0},
                "lengthCm": 300,
                "constructionState": state,
            }
        ]
    )
    with pytest.raises(ValidationError, match="constructionThicknessCm is required"):
        PlanPayload.model_validate(raw)


def test_legacy_explicit_thickness_is_promoted_for_construction_wall():
    raw = _base(
        walls=[
            {
                "id": "w1",
                "a": {"x": 0, "y": 0},
                "b": {"x": 100, "y": 0},
                "lengthCm": 300,
                "constructionState": "new",
                "thicknessMm": 120,
            }
        ]
    )
    payload = PlanPayload.model_validate(raw)
    assert payload.walls[0].constructionThicknessCm == 12
