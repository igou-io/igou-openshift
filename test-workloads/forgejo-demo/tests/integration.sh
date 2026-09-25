#!/usr/bin/env bash
# Run against a fresh disposable Docker container, or --existing after demo.sh seed.
set -euo pipefail
set +x
root=$(cd "$(dirname "$0")/.." && pwd)
container=${1:?Pass test container name or --existing}
export FORGEJO_URL=${FORGEJO_URL:?Set local test URL}
export COLLECTION_SOURCE=${COLLECTION_SOURCE:-$root/fixtures/collection}
if [[ $container == --existing ]]; then
  : "${FORGEJO_TOKEN:?Set admin token}" "${AGENT_TOKEN:?Set agent token}" "${DEMO_PASSWORD:?Set demo password}"
else
export DEMO_PASSWORD
DEMO_PASSWORD=$(openssl rand -hex 24)
printf '%s\n' "$DEMO_PASSWORD" | docker exec -i "$container" sh -c '
  read -r password
  forgejo --config /var/lib/gitea/custom/conf/app.ini admin user create --username demo-admin --email admin@example.test --password "$password" --admin --must-change-password=false
' >/dev/null
FORGEJO_TOKEN=$(docker exec "$container" forgejo --config /var/lib/gitea/custom/conf/app.ini admin user generate-access-token --username demo-admin --token-name integration-test --scopes all --raw)
fi
export FORGEJO_TOKEN
"$root/scripts/seed.sh"
"$root/scripts/seed.sh"
# shellcheck source=../scripts/api.sh
source "$root/scripts/api.sh"
api GET /admin/users | jq -e 'length == 4' >/dev/null
api GET /users/demo-owner/repos | jq -e 'length == 2' >/dev/null
repo=demo-owner/ansible-collection-demo
api GET "/repos/$repo/contents/galaxy.yml" | jq -e '.type == "file"' >/dev/null
api GET "/repos/$repo/collaborators/demo-agent/permission" | jq -e '.permission == "write"' >/dev/null
export WEBHOOK_SECRET
WEBHOOK_SECRET=${WEBHOOK_SECRET:-$(openssl rand -hex 24)}
"$root/scripts/webhook.sh" "$repo" "${WEBHOOK_TEST_URL:-http://127.0.0.1:9999/events}"
"$root/scripts/webhook.sh" "$repo" "${WEBHOOK_TEST_URL:-http://127.0.0.1:9999/events}"
api GET "/repos/$repo/hooks" | jq -e 'length == 1 and (.[0].events | index("package") != null and index("action_run_success") != null and index("issues") != null and index("pull_request") != null)' >/dev/null
file=$(mktemp)
trap 'rm -f "$file"' EXIT
printf 'Document the collection prerequisites. Acceptance: update README and open a PR.\n' > "$file"
"$root/scripts/issue.sh" "$repo" 'Document prerequisites' "$file" >/dev/null
api GET "/repos/$repo/issues" | jq -e 'length == 1' >/dev/null
# Verify the agent can author a branch, commit and PR using its own scoped token.
if [[ $container == --existing ]]; then
  FORGEJO_TOKEN=$AGENT_TOKEN
else
  FORGEJO_TOKEN=$(docker exec "$container" forgejo --config /var/lib/gitea/custom/conf/app.ini admin user generate-access-token --username demo-agent --token-name integration-agent --scopes write:repository,write:issue,read:user --raw)
fi
export FORGEJO_TOKEN
api POST "/repos/$repo/branches" '{"new_branch_name":"demo-change","old_branch_name":"main"}' >/dev/null
api POST "/repos/$repo/contents/DEMO.md" '{"branch":"demo-change","message":"Document demo","content":"IyBEZW1vCg=="}' >/dev/null
api POST "/repos/$repo/pulls" '{"head":"demo-change","base":"main","title":"Document demo","body":"Closes #1"}' | jq -e '.user.login == "demo-agent"' >/dev/null
printf 'PASS: repeatable seed, users, collection, collaborators, all-event hook, issue, agent commit and PR\n'
