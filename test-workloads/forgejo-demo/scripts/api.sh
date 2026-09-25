#!/usr/bin/env bash
# Shared API client. Authentication stays out of command arguments and output.
set -euo pipefail
set +x
: "${FORGEJO_URL:?Set FORGEJO_URL}"
: "${FORGEJO_TOKEN:?Set FORGEJO_TOKEN}"
FORGEJO_URL=${FORGEJO_URL%/}
api() {
  local method=$1 path=$2 body=${3:-} response status
  response=$(mktemp)
  status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
    --config <(printf 'header = "Authorization: token %s"\n' "$FORGEJO_TOKEN") \
    -H 'Content-Type: application/json' -X "$method" \
    ${body:+--data-binary @-} -o "$response" -w '%{http_code}' \
    "$FORGEJO_URL/api/v1$path" <<< "$body") || { rm -f "$response"; return 1; }
  if [[ $status != 2* ]]; then
    printf 'Forgejo API %s %s failed (HTTP %s)\n' "$method" "$path" "$status" >&2
    rm -f "$response"
    return 1
  fi
  cat "$response"
  rm -f "$response"
}
