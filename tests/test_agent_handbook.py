from backend.agent.prompt_loader import (
    AUTONOMOUS_REPAIR_BUDGET,
    INSTRUCTION_VERSION,
    build_system_prompt,
    select_examples,
)


def test_handbook_contains_authority_and_autonomy_policy():
    prompt = build_system_prompt({"warnings": ["gap at corner"], "geometryScore": 60})
    assert INSTRUCTION_VERSION in prompt
    assert AUTONOMOUS_REPAIR_BUDGET == 0.30
    assert "30%" in prompt
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
