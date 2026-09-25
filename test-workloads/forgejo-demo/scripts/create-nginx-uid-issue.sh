#!/usr/bin/env bash
# Explicit demo trigger. Each invocation opens a new feature request.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
export FORGEJO_URL=${FORGEJO_URL:-https://forgejo-demo.apps.ocp.igou.systems}
if [[ -z ${FORGEJO_TOKEN:-} ]]; then
  FORGEJO_TOKEN=$(cat "$root/.state/admin-token")
  export FORGEJO_TOKEN
fi
exec "$root/scripts/issue.sh" "${1:-demo-owner/ansible-collection-demo}" \
  'Allow configuring the nginx worker UID' "$root/fixtures/nginx-uid-issue.md"
