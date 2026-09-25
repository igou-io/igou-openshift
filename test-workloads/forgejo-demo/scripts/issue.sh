#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=api.sh
source "$(dirname "$0")/api.sh"
repo=${1:?Pass owner/repo}
title=${2:?Pass issue title}
body_file=${3:?Pass a Markdown file containing the task and acceptance criteria}
[[ $repo =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]] || exit 2
api POST "/repos/$repo/issues" "$(jq -n --arg title "$title" --rawfile body "$body_file" '{title:$title,body:$body}')" | jq -r .html_url
