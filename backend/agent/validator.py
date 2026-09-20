from __future__ import annotations

from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult


def measurements_preserved(plan: NormalizedPlan, solved: SolverResult, tolerance_mm: float) -> tuple[bool, str]:
    max_error = max((float(meta.get("lengthErrorMm", 0)) for meta in solved.wall_meta.values()), default=0.0)
    if max_error > tolerance_mm:
        return False, f"length error {max_error:.3f} mm exceeds tolerance"
    return True, "ok"
