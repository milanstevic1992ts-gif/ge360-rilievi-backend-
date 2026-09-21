# Architecture

```text
GE360 OPEN PLAN3D
  -> FastAPI
  -> immutable RAW storage
  -> internal async job queue
  -> normalizer
  -> NetworkX topology
  -> deterministic SciPy geometry solver
  -> optional constrained Ollama tool loop
  -> validator + geometry score
  -> authoritative GE360 PlanModel
  -> processed JSON / DXF / SVG / PNG / PDF / plan3d.json
  -> versioned filesystem + SQLite
  -> frontend
```

## Geometry rules

1. Declared metric values have highest priority.
2. Topology and endpoint proximity come second.
3. Orthogonal/parallel interpretation is used only when the sketch supports it.
4. A real diagonal remains diagonal.
5. A cycle whose measured lengths conflict with inferred angle constraints is `NEEDS_REVIEW`.
6. The solver and AI agent never edit authoritative source wall lengths or opening measurements to force closure.

## Internal unit

All solved geometry is millimetres. Frontend centimetres are converted once at the normalization boundary. Adapters may convert units only at their own boundary and may never write those converted values back as authoritative GE360 measurements.

## Jobs

V1 uses a SQLite-backed persistent job queue executed by an in-process `ThreadPoolExecutor`. Each job stores the RAW revision hash and snapshot it must process. Multiple newer revisions of the same `planId` may wait in `QUEUED`, but only one is `PROCESSING` at a time; jobs survive service restarts without changing the HTTP contract.

## AI boundary

Ollama is optional. The default local model is Qwen3:8b. The planner receives inspected facts plus the versioned GE360 floorplan handbook and case-relevant few-shot examples, and may only propose named GE360 tools. Mutation happens on a deep-copied candidate. The candidate is accepted only if declared wall lengths and opening measurements are unchanged, topology/openings remain valid and the geometry score improves. Maximum five iterations. The agent is deliberately proactive. The 30% value is the tolerated residual error/uncertainty ratio for problematic geometric elements, not a modification budget. The agent may try multiple sandbox repairs; above the threshold the best result is still produced and marked NEEDS_REVIEW. Missing deterministic tools are reported as capability gaps, not replaced by invented coordinates. Ollama unavailability never blocks deterministic exports.

## Storage/versioning

`<GE360_DATA_DIR>/<planId>/` contains:

- `raw/original.json`: immutable first payload;
- `raw/latest.json` and immutable `received-*` snapshots;
- `versions/NNN/`: each processing attempt and its manifest/artifacts;
- `current/`: published copy of the latest successful/review result;
- `logs/processing.jsonl`: processing audit log.

GLB and Telegram are deliberately outside the V1 critical path. The 3D contract is `plan3d.json`.
