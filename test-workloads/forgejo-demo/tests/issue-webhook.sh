#!/usr/bin/env bash
# Requires the optional receiver to be running with the matching WEBHOOK_SECRET.
# Creates one real issue, waits for its signed event, then closes the test issue.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=../scripts/api.sh
source "$root/scripts/api.sh"
repo=demo-owner/ansible-collection-demo
server=$(oc whoami --show-server)
oc whoami
[[ $server == "${EXPECTED_SERVER:-https://api.ocp.igou.systems:6443}" ]] || exit 2
: "${WEBHOOK_SECRET:?Set the same secret as the test receiver}"
"$root/scripts/webhook.sh" "$repo" http://demo-receiver.forgejo-demo.svc:39991/events
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
issue=$(api POST "/repos/$repo/issues" '{"title":"Verify issue-opened webhook delivery","body":"Automated webhook smoke test. Closed after a signed issues/opened delivery is confirmed."}')
number=$(jq -er .number <<< "$issue")
url=$(jq -er .html_url <<< "$issue")
for ((attempt=0; attempt<30; attempt++)); do
  logs=$(oc -n forgejo-demo logs deployment/demo-receiver --since-time="$started" --tail=500 --prefix=false)
  if record=$(jq -Rsce --arg repo "$repo" --argjson number "$number" \
    'split("\n") | map(fromjson? | select(.event == "issues" and .action == "opened" and .repository == $repo and .issue == $number and .signature_verified == true and (.delivery | type == "string" and length > 0))) | first // empty' <<< "$logs"); then
    printf '%s\n' "$record"
    api PATCH "/repos/$repo/issues/$number" '{"state":"closed"}' >/dev/null
    printf 'PASS: signed issues/opened delivery for %s (test issue now closed)\n' "$url"
    exit 0
  fi
  sleep 2
done
printf 'No matching signed issues/opened delivery within 60 seconds: %s\n' "$url" >&2
exit 1
