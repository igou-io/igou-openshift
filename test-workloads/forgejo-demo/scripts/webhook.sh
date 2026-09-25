#!/usr/bin/env bash
# Usage: webhook.sh owner/repo https://receiver.example/events
set -euo pipefail
source "$(dirname "$0")/api.sh"
repo=${1:?Pass owner/repo}
url=${2:?Pass webhook URL}
[[ $repo =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]] || exit 2
[[ $url == https://* || $url == http://* ]] || exit 2
: "${WEBHOOK_SECRET:?Set WEBHOOK_SECRET for payload signatures}"
# Forgejo 16 has no API wildcard. These umbrella events include all issue/PR subevents.
body=$(jq -n --arg url "$url" --arg secret "$WEBHOOK_SECRET" '{type:"forgejo",active:true,branch_filter:"*",config:{url:$url,content_type:"json",secret:$secret},events:["create","delete","fork","push","issues","pull_request","wiki","repository","release","package","action_run_failure","action_run_recover","action_run_success"]}')
# Locate the same destination across every page; preserve unrelated hooks.
page=1
ids=()
while :; do
  hooks=$(api GET "/repos/$repo/hooks?limit=50&page=$page")
  while IFS= read -r id; do [[ -z $id ]] || ids+=("$id"); done < <(jq -r --arg url "$url" '.[] | select(.config.url == $url) | .id' <<< "$hooks")
  [[ $(jq length <<< "$hooks") == 50 ]] || break
  ((page+=1))
done
# Recreate rather than PATCH: Forgejo 16's edit handler omits package/actions events.
# Create first, so a failed create leaves the previous integration in place.
api POST "/repos/$repo/hooks" "$body" >/dev/null
for id in "${ids[@]}"; do api DELETE "/repos/$repo/hooks/$id" >/dev/null; done
printf 'Configured all Forgejo 16 repository webhook events for %s\n' "$repo"
