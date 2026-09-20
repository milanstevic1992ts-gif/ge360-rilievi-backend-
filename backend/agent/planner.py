from __future__ import annotations

from backend.agent.ollama import OllamaClient
from backend.agent.prompts import SYSTEM_PROMPT
from backend.agent.tools import find_near_endpoints, inspect_plan
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult


class AgentPlanner:
    def __init__(self, client: OllamaClient):
        self.client = client

    def propose(self, plan: NormalizedPlan, solved: SolverResult, score: float) -> list[dict] | None:
        context = {
            "plan": inspect_plan(plan, solved),
            "nearEndpoints": find_near_endpoints(plan, max_gap_mm=500.0),
            "warnings": solved.warnings,
            "geometryScore": score,
        }
        reply = self.client.propose(SYSTEM_PROMPT, context)
        if reply is None:
            return None
        operations = reply.get("operations")
        if not isinstance(operations, list):
            return []
        return [op for op in operations if isinstance(op, dict)]
