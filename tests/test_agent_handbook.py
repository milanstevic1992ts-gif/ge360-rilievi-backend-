from backend.agent.prompt_loader import (
    MAX_ERROR_TOLERANCE_RATIO,
    INSTRUCTION_VERSION,
    build_system_prompt,
    select_examples,
)


def test_handbook_contains_authority_and_autonomy_policy():
    prompt = build_system_prompt({"warnings": ["gap at corner"], "geometryScore": 60})
    assert INSTRUCTION_VERSION in prompt
    assert MAX_ERROR_TOLERANCE_RATIO == 0.30
    assert "30%" in prompt
    assert "non un repair budget" in prompt.lower()
    assert "Non modificare né inventare" in prompt
    assert "coordinate definitive" in prompt


def test_diagonal_example_selected():
    ids = {row["id"] for row in select_examples({"warnings": ["real diagonal angle conflict"]})}
    assert "real-diagonal" in ids


def test_opening_example_selected():
    ids = {row["id"] for row in select_examples({"warnings": ["Opening door offset invalid"]})}
    assert "opening-offset" in ids


def test_capability_gap_contract_present():
    prompt = build_system_prompt({"warnings": ["T junction needs split"]})
    assert "missingCapabilities" in prompt
    assert "split_wall_at_intersection" in prompt


def test_agent_retains_assessment_and_missing_capabilities():
    from backend.agent import GeometryAgent
    from backend.geometry.normalizer import normalize_payload
    from backend.geometry.solver import solve_geometry
    from backend.geometry.topology import build_topology
    from backend.models import PlanPayload

    class CapabilityClient:
        def propose(self, system_prompt, context):
            assert "30%" in system_prompt
            return {
                "operations": [],
                "assessment": {
                    "estimatedProblemRatio": 0.2,
                    "needsHumanReview": True,
                },
                "missingCapabilities": [
                    {
                        "name": "split_wall_at_intersection",
                        "reason": "T-junction requires deterministic split",
                        "priority": "HIGH",
                    }
                ],
            }

    payload = PlanPayload.model_validate({
        "version": 4,
        "planId": "capability-gap",
        "walls": [
            {"id": "w1", "a": {"x": 0, "y": 0}, "b": {"x": 200, "y": 0}, "lengthCm": 200},
            {"id": "w2", "a": {"x": 100, "y": 100}, "b": {"x": 100, "y": 0}, "lengthCm": 100},
        ],
    })
    plan = normalize_payload(payload)
    topology = build_topology(plan)
    solved = solve_geometry(plan, topology)
    run = GeometryAgent(CapabilityClient()).improve(plan, topology, solved)

    assert run.assessment["estimatedProblemRatio"] == 0.2
    assert run.missing_capabilities[0]["name"] == "split_wall_at_intersection"
    assert run.accepted == []
