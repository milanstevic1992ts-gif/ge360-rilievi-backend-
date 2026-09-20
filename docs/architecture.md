# Architecture

GE360 Rilievo smartphone -> FastAPI + X-GE360-API-Key -> immutable RAW storage -> normalizer -> NetworkX topology -> deterministic SciPy geometry solver -> optional constrained Ollama agent -> validator + geometry score -> single GE360 PlanModel -> JSON/SVG/DXF/PNG/PDF + plan3d/GLB -> versioned filesystem + SQLite -> frontend/Telegram.

## Geometry rules

1. Declared metric values have highest priority.
2. Topology and endpoint proximity come second.
3. Orthogonal/parallel interpretation is used only when the sketch supports it.
4. A real diagonal remains diagonal.
5. A cycle whose measured lengths conflict with inferred angle constraints is NEEDS_REVIEW.
6. The solver never edits sourceLengthCm or opening width/offset values to force closure.

## Internal unit

All solved geometry is millimetres. Frontend centimetres are converted once at the normalization boundary.

## Storage

<GE360_DATA_DIR>/<planId>/ contains raw/original.json (first payload, immutable), raw/latest.json, immutable received-* snapshots, current outputs, numbered versions and logs/processing.jsonl.
