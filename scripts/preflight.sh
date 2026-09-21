#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${GE360_ENV_FILE:-/etc/ge360-rilievi-backend/ge360.env}"

read_env() {
  local key="$1"
  local default="${2:-}"
  local value=""

  if [[ -r "$ENV_FILE" ]]; then
    value="$(
      grep -E "^${key}=" "$ENV_FILE" 2>/dev/null |
      tail -n1 |
      cut -d= -f2- || true
    )"
    value="${value%$'\r'}"

    if [[ "$value" =~ ^\".*\"$ ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf '%s' "${value:-$default}"
}

require="$(read_env GE360_REQUIRE_API_KEY true)"
case "${require,,}" in
  0|false|no|off) exit 0 ;;
esac

api_key="$(read_env GE360_API_KEY '')"
[[ -n "$api_key" ]] && exit 0

data_dir="$(read_env GE360_DATA_DIR /opt/ge360/data/rilievi)"
key_file="$(read_env GE360_API_KEY_FILE "$data_dir/.api-key")"

if [[ -r "$key_file" ]]; then
  key="$(tr -d '\r\n' < "$key_file")"
  [[ -n "$key" ]] && exit 0
fi

echo "GE360 SECURITY: API key required but missing: $key_file" >&2
exit 78
