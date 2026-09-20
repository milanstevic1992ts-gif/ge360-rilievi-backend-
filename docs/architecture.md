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

V1 uses an in-process `ThreadPoolExecutor`. `POST /process` first marks the record `QUEUED`, then a worker transitions it to `PROCESSING`. Only one active local job is allowed per `planId`. This is intentionally isolated behind `JobManager` so a future external queue can replace it without changing the API contract.

## AI boundary

Ollama is optional. The planner receives inspected facts and may only propose named GE360 tools. Mutation happens on a deep-copied candidate. The candidate is accepted only if declared wall lengths and opening measurements are unchanged, topology/openings remain valid and the geometry score improves. Maximum five iterations. Ollama unavailability never blocks deterministic exports.

## Storage/versioning

`<GE360_DATA_DIR>/<planId>/` contains:

- `raw/original.json`: immutable first payload;
- `raw/latest.json` and immutable `received-*` snapshots;
- `versions/NNN/`: each processing attempt and its manifest/artifacts;
- `current/`: published copy of the latest successful/review result;
- `logs/processing.jsonl`: processing audit log.

GLB and Telegram are deliberately outside the V1 critical path. The 3D contract is `plan3d.json`.
