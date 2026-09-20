from __future__ import annotations

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.models import PlanPayload
from backend.geometry.normalizer import normalize_payload
from backend.geometry.topology import build_topology
from backend.geometry.solver import solve_geometry
from backend.cad.model import build_cad_model
from backend.geometry.validator import validate_geometry


def make_payload(walls, *, plan_id="test-plan", openings=None, rooms=None, wall_height_m=2.7):
    return PlanPayload.model_validate({
        "version":4,"kind":"ge360-rough-survey","planId":plan_id,"name":"Test",
        "walls":walls,"openings":openings or [],"rooms":rooms or [],"notes":[],"wallHeightM":wall_height_m,
    })


def solve_payload(payload, snap=250):
    normalized=normalize_payload(payload,snap_tolerance_mm=snap)
    topology=build_topology(normalized)
    solved=solve_geometry(normalized,topology,length_tolerance_mm=0.5)
    model=build_cad_model(normalized,solved)
    validation=validate_geometry(normalized,solved,model.rooms,length_tolerance_mm=0.5)
    model.needsReview=model.needsReview or validation["needsReview"]
    return normalized,topology,solved,model,validation

@pytest.fixture
def rect_2x3_walls():
    return [
        {"id":"w1","a":{"x":0,"y":0},"b":{"x":200,"y":0},"lengthCm":200},
        {"id":"w2","a":{"x":200,"y":0},"b":{"x":200,"y":300},"lengthCm":300},
        {"id":"w3","a":{"x":200,"y":300},"b":{"x":0,"y":300},"lengthCm":200},
        {"id":"w4","a":{"x":0,"y":300},"b":{"x":0,"y":0},"lengthCm":300},
    ]
