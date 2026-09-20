#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="${GE360_SMOKE_PORT:-18796}"
BASE="http://${HOST}:${PORT}"
API="${BASE}/api/v1"
KEY="ge360-smoke-test-key"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${ROOT}/tests/fixtures/openplan3d-v4.json"
TMP="$(mktemp -d)"
PID=""

cleanup() {
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" 2>/dev/null || true
    wait "${PID}" 2>/dev/null || true
  fi
  rm -rf "${TMP}"
}
trap cleanup EXIT

export GE360_API_KEY="${KEY}"
export GE360_DATA_DIR="${TMP}/data"
export GE360_DB_PATH="${TMP}/data/ge360.sqlite3"
export GE360_AI_ENABLED=false
export GE360_CORS_ORIGINS="http://localhost"
export GE360_JOB_WORKERS=1

cd "${ROOT}"
python -m uvicorn backend.main:app --host "${HOST}" --port "${PORT}" >"${TMP}/uvicorn.log" 2>&1 &
PID=$!

for _ in $(seq 1 100); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then break; fi
  sleep 0.05
done
curl -fsS "${BASE}/healthz" >/dev/null

unauth="$(curl -s -o /dev/null -w '%{http_code}' "${API}/health")"
[[ "${unauth}" == "401" ]]

queued="$(curl -fsS -X POST "${API}/plans/refine"   -H "Content-Type: application/json"   -H "X-GE360-API-Key: ${KEY}"   --data-binary "@${FIXTURE}")"

JOB_ID="$(python -c 'import json,sys; d=json.load(sys.stdin); assert d["status"] in {"QUEUED","PROCESSING"}; assert d["statusUrl"]; assert d["viewerUrl"]; print(d["jobId"])' <<<"${queued}")"
PLAN_ID="$(python -c 'import json,sys; print(json.load(sys.stdin)["planId"])' <<<"${queued}")"

state=""
for _ in $(seq 1 300); do
  state="$(curl -fsS "${API}/jobs/${JOB_ID}" -H "X-GE360-API-Key: ${KEY}")"
  job_status="$(python -c 'import json,sys; print(json.load(sys.stdin)["status"])' <<<"${state}")"
  if [[ "${job_status}" == "DONE" || "${job_status}" == "ERROR" ]]; then break; fi
  sleep 0.05
done
python -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="DONE", d' <<<"${state}"

status="$(curl -fsS "${API}/plans/${PLAN_ID}" -H "X-GE360-API-Key: ${KEY}")"
python -c 'import json,sys; d=json.load(sys.stdin); assert d["status"]=="PROCESSED", d; assert d["summary"]=={"rooms":1,"floorAreaM2":6.0}; assert d["files"]["viewer"]; assert d["files"]["glb"] is None' <<<"${status}"

mkdir -p "${TMP}/artifacts"
for artifact in processed preview png svg pdf dxf 3d; do
  curl -fsS "${API}/plans/${PLAN_ID}/${artifact}"     -H "X-GE360-API-Key: ${KEY}"     -o "${TMP}/artifacts/${artifact}"
  test -s "${TMP}/artifacts/${artifact}"
done

python - "${TMP}/artifacts/processed" "${TMP}/artifacts/dxf" "${TMP}/artifacts/3d" <<'PY'
import json, sys
import ezdxf

processed=json.load(open(sys.argv[1],encoding="utf-8"))
lengths={w["id"]:w["declaredLengthMm"] for w in processed["walls"]}
assert lengths=={"w1":2000.0,"w2":3000.0,"w3":2000.0,"w4":3000.0}, lengths
door=next(o for o in processed["openings"] if o["id"]=="door-1")
assert door["widthMm"]==800.0
assert door["offsetMm"]==1000.0

doc=ezdxf.readfile(sys.argv[2])
audit=doc.audit()
assert not audit.has_errors, audit.errors

plan3d=json.load(open(sys.argv[3],encoding="utf-8"))
assert sorted(round(w["length"]) for w in plan3d["walls"])==[2000,2000,3000,3000]
assert all(round(w["height"])==2700 for w in plan3d["walls"])
PY

echo "GE360 HTTP smoke OK: ${PLAN_ID}"
