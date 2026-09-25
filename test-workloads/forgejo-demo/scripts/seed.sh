#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=api.sh
source "$(dirname "$0")/api.sh"
root=$(cd "$(dirname "$0")/.." && pwd)
config=${SEED_CONFIG:-$root/seed.json}
COLLECTION_SOURCE=${COLLECTION_SOURCE:-$root/fixtures/collection}
[[ -f $COLLECTION_SOURCE/galaxy.yml ]] || { echo 'Source must contain galaxy.yml' >&2; exit 2; }
if [[ $COLLECTION_SOURCE != "$root/fixtures/collection" ]]; then
  git -C "$COLLECTION_SOURCE" rev-parse --verify HEAD >/dev/null
fi
jq -e '.users | length > 0' "$config" >/dev/null
users='[]'
page=1
while :; do
  batch=$(api GET "/admin/users?limit=50&page=$page")
  users=$(jq -s 'add' <(printf '%s' "$users") <(printf '%s' "$batch"))
  [[ $(jq length <<< "$batch") == 50 ]] || break
  ((page+=1))
done
while IFS= read -r user; do
  name=$(jq -r .username <<< "$user")
  if ! jq -e --arg name "$name" 'any(.[]; .login == $name)' <<< "$users" >/dev/null; then
    body=$(jq --arg password "$name" '. + {password:$password,must_change_password:false,send_notify:false}' <<< "$user")
    api POST /admin/users "$body" >/dev/null
  else
    body=$(jq -n --arg name "$name" '{password:$name,must_change_password:false}')
    api PATCH "/admin/users/$name" "$body" >/dev/null
  fi
done < <(jq -c '.users[]' "$config")
# Git uses an askpass helper: no credentials in clone URLs or persistent remotes.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/askpass" <<'ASKPASS'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' demo-admin ;;
  *) printf '%s\n' "$FORGEJO_TOKEN" ;;
esac
ASKPASS
chmod 700 "$tmp/askpass"
export GIT_ASKPASS="$tmp/askpass" GIT_TERMINAL_PROMPT=0
while IFS= read -r repo; do
  owner=$(jq -r .owner <<< "$repo")
  name=$(jq -r .name <<< "$repo")
  [[ $owner/$name =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]] || exit 2
  # Enumerate using the admin's read access, including private repos.
  page=1; found=false
  while :; do
    repos=$(api GET "/users/$owner/repos?limit=50&page=$page")
    if jq -e --arg name "$name" 'any(.[]; .name == $name)' <<< "$repos" >/dev/null; then found=true; break; fi
    [[ $(jq length <<< "$repos") == 50 ]] || break
    ((page+=1))
  done
  if [[ $found == false ]]; then
    api POST "/admin/users/$owner/repos" "$(jq '{name,description,private:true,auto_init:false,default_branch:"main"}' <<< "$repo")" >/dev/null
  fi
  refs=$(git -c credential.helper= ls-remote "$FORGEJO_URL/$owner/$name.git")
  if [[ -z $refs ]]; then
    source=$(jq -r '.source // ""' <<< "$repo")
    [[ $name != ansible-collection-demo || -n $source ]] || source=$COLLECTION_SOURCE
    work=$tmp/$name
    git init -q -b main "$work"
    if [[ -n $source ]]; then
      # Snapshot tracked HEAD only; omit .git, untracked secrets, and old history.
      if [[ $source == "$root/fixtures/collection" ]]; then
        tar -C "$source" --exclude=.git --exclude=.venv --exclude=.ansible --exclude=.cache --exclude=__pycache__ --exclude='*.pyc' --exclude='*.tar.gz' -cf - . | tar -xf - -C "$work"
      else
        git -C "$source" archive HEAD | tar -x -C "$work"
      fi
    else
      printf '# %s\n\n%s\n' "$name" "$(jq -r .description <<< "$repo")" > "$work/README.md"
    fi
    git -C "$work" add .
    git -C "$work" -c user.name='Demo Maintainer' -c user.email=owner@example.test commit -qm 'Seed demo baseline'
    git -C "$work" -c credential.helper= push -q "$FORGEJO_URL/$owner/$name.git" main
  fi
  while IFS= read -r collaborator; do
    api PUT "/repos/$owner/$name/collaborators/$collaborator" '{"permission":"write"}' >/dev/null
  done < <(jq -r '.collaborators[]' <<< "$repo")
done < <(jq -c '.repositories[]' "$config")
if [[ -n ${WEBHOOK_URL:-} ]]; then
  "$root/scripts/webhook.sh" demo-owner/ansible-collection-demo "$WEBHOOK_URL"
fi
echo 'Seed complete. Create the trigger issue after the agent integration is ready.'
