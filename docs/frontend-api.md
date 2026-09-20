# GE360 Rilievo frontend → backend contract

Frontend inspected: milanstevic1992ts-gif/ge360-open-plan3d, branch main. The current frontend uses a base serverUrl pointing to /api/v1, GET /health, POST /plans/refine and POST /notes/rewrite.

Payload v4 fields: version, kind, planId, name, updatedAt, rawStrokes, walls, openings, rooms, notes, wallHeightM, surfaces, summary.

Authoritative fields include wall lengthCm, opening widthCm and offsetCm, plus user-provided heights/sill heights. Smartphone coordinates are never metric truth.

## Authentication

Every /api/v1/* endpoint requires X-GE360-API-Key. GET /healthz is unauthenticated for local supervision.

## Existing frontend compatibility

GET /api/v1/health
POST /api/v1/plans/refine
POST /api/v1/notes/rewrite

POST /plans/refine saves RAW immediately, queues processing and returns planId, jobId and PROCESSING.

## Preferred new flow

1. POST /api/v1/plans
2. POST /api/v1/plans/{planId}/process
3. Poll GET /api/v1/plans/{planId} or /api/v1/jobs/{jobId}
4. Fetch outputs when PROCESSED or NEEDS_REVIEW.

Statuses: RAW, PROCESSING, PROCESSED, NEEDS_REVIEW, ERROR.

Outputs: processed, preview, svg, dxf, pdf, 3d, glb and versions endpoints.

## Opening metric rule

referenceEnd=a: centerFromStart = offset + width/2.
referenceEnd=b: centerFromStart = wallLength - offset - width/2.

The backend recomputes the opening point on the solved wall from those metric values.
