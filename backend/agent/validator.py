from __future__ import annotations

from dataclasses import dataclass

from backend.cad.model import build_cad_model
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.score import geometry_score
from backend.geometry.solver import SolverResult
from backend.geometry.topology import TopologyResult
from backend.geometry.validator import validate_geometry


@dataclass
class CandidateValidation:
    accepted: bool
    reason: str
    score: float


def authoritative_snapshot(plan: NormalizedPlan) -> dict:
    return {
        "lengths": {w.id: w.length_mm for w in plan.walls},
        "openings": {
            str(o.get("id")): (o.get("wallId"), o.get("widthCm"), o.get("offsetCm"), o.get("heightCm"), o.get("heightMm"))
            for o in plan.openings
        },
    }


def measurements_preserved(snapshot: dict, plan: NormalizedPlan, solved: SolverResult, tolerance_mm: float) -> tuple[bool, str]:
    if snapshot["lengths"] != {w.id: w.length_mm for w in plan.walls}:
        return False, "authoritative declared lengths changed"
    current_openings = {
        str(o.get("id")): (o.get("wallId"), o.get("widthCm"), o.get("offsetCm"), o.get("heightCm"), o.get("heightMm"))
        for o in plan.openings
    }
    if snapshot["openings"] != current_openings:
        return False, "authoritative opening measurements changed"
    max_error = max((float(meta.get("lengthErrorMm", 0)) for meta in solved.wall_meta.values()), default=0.0)
    if max_error > tolerance_mm:
        return False, f"length error {max_error:.3f} mm exceeds tolerance"
    return True, "ok"


def validate_candidate(snapshot: dict, plan: NormalizedPlan, topology: TopologyResult, solved: SolverResult,
                       baseline_score: float, tolerance_mm: float) -> CandidateValidation:
    preserved, reason = measurements_preserved(snapshot, plan, solved, tolerance_mm)
    if not preserved:
        return CandidateValidation(False, reason, 0.0)
    if any(w.start_node == w.end_node for w in plan.walls):
        return CandidateValidation(False, "topology contains a collapsed wall", 0.0)
    model = build_cad_model(plan, solved)
    wall_lengths = {w.id: w.declaredLengthMm for w in model.walls}
    for opening in model.openings:
        if opening.offsetMm < -tolerance_mm or opening.offsetMm + opening.widthMm > wall_lengths[opening.wallId] + tolerance_mm:
            return CandidateValidation(False, f"opening {opening.id} no longer fits its wall", 0.0)
    validation = validate_geometry(plan, solved, model.rooms, length_tolerance_mm=tolerance_mm)
    score = geometry_score(validation, len(model.rooms))
    if score <= baseline_score + 0.001:
        return CandidateValidation(False, "geometry score did not improve", score)
    return CandidateValidation(True, "ok", score)
