from backend.agent.prompt_loader import build_system_prompt

# Backward-compatible constant for code/tests that still import SYSTEM_PROMPT.
# Runtime planning uses build_system_prompt(context) so the agent receives
# case-relevant examples in addition to the versioned handbook.
SYSTEM_PROMPT = build_system_prompt()
