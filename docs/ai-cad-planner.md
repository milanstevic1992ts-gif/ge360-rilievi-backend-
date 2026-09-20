# GE360 AI CAD copilot

GE360 uses local Ollama with the model locked to `qwen3:8b`. Qwen interprets. GE360 calculates, validates, previews, versions and saves.

## Anti-stall best-effort
The default behavior is useful work instead of a dead end. Missing tool calls, Ollama timeout, ambiguous targets, critic disagreement or one failed candidate operation degrade to deterministic fallback. Low-confidence work remains visible as a candidate/preview and can be marked NEEDS_REVIEW. Unknown normal site instructions are preserved as structured annotations.

Unsafe execution remains impossible because no shell, Python, SQL, arbitrary HTTP, eval/exec or direct database/file mutation tools exist.

## Intelligence
- semantic scene graph for wall/room/opening relations;
- ranked entity resolver;
- planner + second-pass critic;
- local SQLite CAD memory;
- specialized planner modes;
- deterministic multi-strategy repair;
- candidate preview and geometry diff;
- force-apply only through explicit API request, always NEEDS_REVIEW when invalid;
- undo/redo over valid versioned source plans;
- immutable original RAW and versioned source-plan.json.

## Flow
instruction -> Qwen planner -> tool registry/Pydantic -> candidate -> topology -> solver -> validator -> deterministic score -> preview -> explicit apply -> version.

Qwen never writes final coordinates.

## API
GET /api/v1/ai/status
POST /api/v1/plans/{plan_id}/ai/plan
GET /api/v1/plans/{plan_id}/ai/candidates/{candidate_id}
GET /api/v1/plans/{plan_id}/ai/candidates/{candidate_id}/preview
POST /api/v1/plans/{plan_id}/ai/candidates/{candidate_id}/apply
POST /api/v1/plans/{plan_id}/undo
POST /api/v1/plans/{plan_id}/redo

Run the local model benchmark with:
`python scripts/run_ai_benchmark.py`
