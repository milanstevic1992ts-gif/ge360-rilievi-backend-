from __future__ import annotations

from dataclasses import dataclass, field

from backend.agent.ollama import OllamaClient
from backend.agent.prompts import SYSTEM_PROMPT
from backend.agent.tools import operation_to_angle_override
from backend.agent.validator import measurements_preserved
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.score import geometry_score
from backend.geometry.solver import SolverResult, solve_geometry
from backend.geometry.topology import TopologyResult
from backend.geometry.rooms import detect_rooms
from backend.geometry.validator import validate_geometry


@dataclass
class AgentRun:
    solved: SolverResult
    proposals: list[dict] = field(default_factory=list)
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    iterations: int = 0
    offline: bool = False


class GeometryAgent:
    def __init__(self, client: OllamaClient, max_iterations: int = 5, length_tolerance_mm: float = 0.5,
                 orthogonal_tolerance_deg: float = 25.0):
        self.client = client
        self.max_iterations = max_iterations
        self.length_tolerance_mm = length_tolerance_mm
        self.orthogonal_tolerance_deg = orthogonal_tolerance_deg

    def _score(self, plan: NormalizedPlan, solved: SolverResult) -> float:
        rooms = detect_rooms(plan, solved)
        validation = validate_geometry(plan, solved, rooms, length_tolerance_mm=self.length_tolerance_mm)
        return geometry_score(validation, len(rooms))

    def improve(self, plan: NormalizedPlan, topology: TopologyResult, solved: SolverResult) -> AgentRun:
        run = AgentRun(solved=solved)
        current = solved
        overrides: dict[str, float] = {}
        current_score = self._score(plan, current)
        for iteration in range(self.max_iterations):
            context = {
                "walls": [{"id": w.id, "lengthMm": w.length_mm, **current.wall_meta[w.id]} for w in plan.walls],
                "warnings": current.warnings,
                "closureErrorMm": current.closure_error_mm,
                "geometryScore": current_score,
            }
            reply = self.client.propose(SYSTEM_PROMPT, context)
            if reply is None:
                run.offline = True
                break
            operations = list(reply.get("operations") or [])
            if not operations:
                break
            changed = False
            for op in operations:
                run.proposals.append(op)
                proposed, reason = operation_to_angle_override(op, plan, current)
                if not proposed:
                    run.rejected.append({"operation": op, "reason": reason})
                    continue
                candidate_overrides = {**overrides, **proposed}
                candidate = solve_geometry(
                    plan, topology,
                    orthogonal_tolerance_deg=self.orthogonal_tolerance_deg,
                    length_tolerance_mm=self.length_tolerance_mm,
                    angle_overrides=candidate_overrides,
                )
                preserved, reason = measurements_preserved(plan, candidate, self.length_tolerance_mm)
                candidate_score = self._score(plan, candidate)
                if preserved and candidate_score > current_score + 0.001:
                    overrides = candidate_overrides
                    current = candidate
                    current_score = candidate_score
                    run.accepted.append({"operation": op, "scoreAfter": candidate_score})
                    changed = True
                else:
                    run.rejected.append({"operation": op, "reason": reason if not preserved else "geometry score did not improve", "scoreAfter": candidate_score})
            run.iterations = iteration + 1
            if not changed:
                break
        run.solved = current
        return run
