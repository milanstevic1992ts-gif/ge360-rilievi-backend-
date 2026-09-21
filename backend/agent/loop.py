from __future__ import annotations

import copy
from dataclasses import dataclass, field

from backend.agent.ollama import OllamaClient
from backend.agent.planner import AgentPlanner
from backend.agent.prompt_loader import MAX_ERROR_TOLERANCE_RATIO, INSTRUCTION_VERSION
from backend.agent.tools import ANGLE_TOOLS, TOPOLOGY_TOOLS, apply_topology_operation, operation_to_angle_override
from backend.agent.validator import authoritative_snapshot, validate_candidate
from backend.cad.model import build_cad_model
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.score import geometry_score
from backend.geometry.solver import SolverResult, solve_geometry
from backend.geometry.topology import TopologyResult, build_topology
from backend.geometry.validator import validate_geometry


@dataclass
class AgentRun:
    plan: NormalizedPlan
    topology: TopologyResult
    solved: SolverResult
    proposals: list[dict] = field(default_factory=list)
    accepted: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    iterations: int = 0
    offline: bool = False
    instruction_version: str = INSTRUCTION_VERSION
    error_tolerance_ratio: float = MAX_ERROR_TOLERANCE_RATIO
    estimated_error_ratio: float = 0.0
    assessment: dict = field(default_factory=dict)
    missing_capabilities: list[dict] = field(default_factory=list)


class GeometryAgent:
    def __init__(self, client: OllamaClient, max_iterations: int = 5, length_tolerance_mm: float = 0.5,
                 orthogonal_tolerance_deg: float = 25.0, solver_kwargs: dict | None = None):
        self.planner = AgentPlanner(client)
        self.solver_kwargs = dict(solver_kwargs or {})
        self.max_iterations = min(5, max(1, max_iterations))
        self.length_tolerance_mm = length_tolerance_mm
        self.orthogonal_tolerance_deg = orthogonal_tolerance_deg

    def _score(self, plan: NormalizedPlan, solved: SolverResult) -> float:
        model = build_cad_model(plan, solved)
        validation = validate_geometry(plan, solved, model.rooms, length_tolerance_mm=self.length_tolerance_mm)
        return geometry_score(validation, len(model.rooms))

    @staticmethod
    def _error_ratio(plan: NormalizedPlan, solved: SolverResult) -> float:
        """Deterministic residual error/uncertainty ratio for agent policy.

        This is deliberately NOT the metric tolerance of a single measured wall
        and NOT a cap on how many sandbox repair attempts the agent may try.
        """
        problematic: set[str] = set()
        for wall in plan.walls:
            meta = solved.wall_meta.get(wall.id, {})
            if (
                bool(meta.get("suspect"))
                or (bool(meta.get("measured", wall.measured)) and not bool(meta.get("withinTolerance", True)))
                or meta.get("lengthSource") == "SKETCH"
                or bool(meta.get("shapeFromSketch"))
            ):
                problematic.add(wall.id)
        for tee in solved.undetermined_tees:
            problematic.update(str(w) for w in tee.get("partitionWallIds", []))
        bad_diagonals = sum(1 for d in solved.diagonal_meta if not d.get("withinTolerance", True))
        denominator = max(1, len(plan.walls) + len(solved.diagonal_meta))
        return round(min(1.0, (len(problematic) + bad_diagonals) / denominator), 4)

    def improve(self, plan: NormalizedPlan, topology: TopologyResult, solved: SolverResult) -> AgentRun:
        working_plan = copy.deepcopy(plan)
        working_topology = topology
        current = solved
        overrides: dict[str, float] = {}
        score = self._score(working_plan, current)
        snapshot = authoritative_snapshot(working_plan)
        snapshot["outOfTolerance"] = sorted(
            wid for wid, meta in solved.wall_meta.items()
            if meta.get("measured", True) and not meta.get("withinTolerance", True)
        )
        run = AgentRun(working_plan, working_topology, current)
        run.estimated_error_ratio = self._error_ratio(working_plan, current)

        for iteration in range(self.max_iterations):
            operations = self.planner.propose(working_plan, current, score)
            run.assessment = dict(self.planner.last_assessment)
            run.missing_capabilities = list(self.planner.last_missing_capabilities)
            if operations is None:
                run.offline = True
                break
            if not operations:
                break
            changed = False
            for operation in operations:
                run.proposals.append(operation)
                name = str(operation.get("tool") or operation.get("type") or "")
                candidate_plan = copy.deepcopy(working_plan)
                candidate_topology = working_topology
                candidate_overrides = dict(overrides)
                if name in ANGLE_TOOLS:
                    proposed, reason = operation_to_angle_override(operation, candidate_plan, current)
                    if not proposed:
                        run.rejected.append({"operation": operation, "reason": reason})
                        continue
                    candidate_overrides.update(proposed)
                elif name in TOPOLOGY_TOOLS:
                    candidate_plan, reason = apply_topology_operation(operation, candidate_plan)
                    if candidate_plan is None:
                        run.rejected.append({"operation": operation, "reason": reason})
                        continue
                    candidate_topology = build_topology(candidate_plan)
                else:
                    run.rejected.append({"operation": operation, "reason": "tool is read-only or unsupported for mutation"})
                    continue

                candidate = solve_geometry(
                    candidate_plan,
                    candidate_topology,
                    orthogonal_tolerance_deg=self.orthogonal_tolerance_deg,
                    length_tolerance_mm=self.length_tolerance_mm,
                    angle_overrides=candidate_overrides,
                    **self.solver_kwargs,
                )
                gate = validate_candidate(snapshot, candidate_plan, candidate_topology, candidate, score, self.length_tolerance_mm)
                if gate.accepted:
                    working_plan = candidate_plan
                    working_topology = candidate_topology
                    current = candidate
                    overrides = candidate_overrides
                    score = gate.score
                    run.estimated_error_ratio = self._error_ratio(working_plan, current)
                    run.accepted.append({
                        "operation": operation,
                        "scoreAfter": score,
                        "errorRatioAfter": run.estimated_error_ratio,
                    })
                    changed = True
                else:
                    run.rejected.append({"operation": operation, "reason": gate.reason, "scoreAfter": gate.score})
            run.iterations = iteration + 1
            if not changed:
                break

        run.plan = working_plan
        run.topology = working_topology
        run.solved = current
        run.estimated_error_ratio = self._error_ratio(working_plan, current)
        return run
