#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${GE360_APP_DIR:-/opt/ge360/ge360-rilievi-backend}"
ENV_FILE="${GE360_ENV_FILE:-$APP_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

require="${GE360_REQUIRE_API_KEY:-true}"
case "${require,,}" in
  0|false|no|off) exit 0 ;;
esac

if [[ -n "${GE360_API_KEY:-}" ]]; then
  exit 0
fi

data_dir="${GE360_DATA_DIR:-/opt/ge360/data/rilievi}"
key_file="${GE360_API_KEY_FILE:-$data_dir/.api-key}"
if [[ -r "$key_file" ]] && [[ -n "$(tr -d '\r\n' < "$key_file")" ]]; then
  exit 0
fi

echo "GE360 SECURITY: API key required but missing. Set GE360_API_KEY or create $key_file" >&2
exit 78
