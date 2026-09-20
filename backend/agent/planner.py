from __future__ import annotations

from backend.agent.ollama import OllamaClient
from backend.agent.prompt_loader import AUTONOMOUS_REPAIR_BUDGET, INSTRUCTION_VERSION, build_system_prompt
from backend.agent.tools import find_near_endpoints, inspect_plan
from backend.geometry.normalizer import NormalizedPlan
from backend.geometry.solver import SolverResult


class AgentPlanner:
    def __init__(self, client: OllamaClient):
        self.client = client
        self.last_assessment: dict = {}
        self.last_missing_capabilities: list[dict] = []

    def propose(self, plan: NormalizedPlan, solved: SolverResult, score: float) -> list[dict] | None:
        context = {
            "plan": inspect_plan(plan, solved),
            "nearEndpoints": find_near_endpoints(plan, max_gap_mm=500.0),
            "warnings": solved.warnings,
            "geometryScore": score,
            "agentPolicy": {
                "instructionVersion": INSTRUCTION_VERSION,
                "autonomousRepairBudget": AUTONOMOUS_REPAIR_BUDGET,
                "strategy": "autonomous-repair-with-deterministic-validation",
            },
        }
        reply = self.client.propose(build_system_prompt(context), context)
        if reply is None:
            return None
        assessment = reply.get("assessment")
        self.last_assessment = assessment if isinstance(assessment, dict) else {}
        missing = reply.get("missingCapabilities")
        self.last_missing_capabilities = [row for row in missing if isinstance(row, dict)] if isinstance(missing, list) else []
        operations = reply.get("operations")
        if not isinstance(operations, list):
            return []
        return [op for op in operations if isinstance(op, dict)]
