#!/usr/bin/env bash
# Run against a fresh disposable Docker container, or --existing after demo.sh seed.
set -euo pipefail
set +x
root=$(cd "$(dirname "$0")/.." && pwd)
container=${1:?Pass test container name or --existing}
export FORGEJO_URL=${FORGEJO_URL:?Set local test URL}
export COLLECTION_SOURCE=${COLLECTION_SOURCE:-$root/fixtures/collection}
if [[ $container == --existing ]]; then
  : "${FORGEJO_TOKEN:?Set admin token}" "${AGENT_TOKEN:?Set agent token}"
else
printf '%s\n' demo-admin | docker exec -i "$container" sh -c '
  read -r password
  forgejo --config /var/lib/gitea/custom/conf/app.ini admin user create --username demo-admin --email admin@example.test --password "$password" --admin --must-change-password=false
' >/dev/null
FORGEJO_TOKEN=$(docker exec "$container" forgejo --config /var/lib/gitea/custom/conf/app.ini admin user generate-access-token --username demo-admin --token-name integration-test --scopes all --raw)
fi
export FORGEJO_TOKEN
"$root/scripts/seed.sh"
"$root/scripts/seed.sh"
# Assert the documented demo passwords work after repeated seeding.
for name in demo-admin demo-owner demo-agent demo-reviewer; do
  curl --fail --silent --show-error --config <(printf 'user = "%s:%s"\n' "$name" "$name") \
    "$FORGEJO_URL/api/v1/user" | jq -e --arg name "$name" '.login == $name' >/dev/null
done
# shellcheck source=../scripts/api.sh
source "$root/scripts/api.sh"
api GET /admin/users | jq -e 'length == 4' >/dev/null
api GET /users/demo-owner/repos | jq -e 'length == 2' >/dev/null
repo=demo-owner/ansible-collection-demo
api GET "/repos/$repo/contents/galaxy.yml" | jq -e '.type == "file"' >/dev/null
api GET "/repos/$repo/collaborators/demo-agent/permission" | jq -e '.permission == "write"' >/dev/null
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
printf 'PASS: repeatable seed, users, collection, collaborators, issue, agent commit and PR\n'
