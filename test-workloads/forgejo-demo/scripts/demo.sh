#!/usr/bin/env bash
# Lifecycle is deliberately fixed to this disposable namespace and PVC.
set -euo pipefail
set +x
root=$(cd "$(dirname "$0")/.." && pwd)
namespace=forgejo-demo
export FORGEJO_URL=${FORGEJO_URL:-https://forgejo-demo.apps.ocp.igou.systems}
state=$root/.state
umask 077
mkdir -p "$state"
cluster() {
  local server
  server=$(oc whoami --show-server)
  oc whoami
  [[ $server == "${EXPECTED_SERVER:-https://api.ocp.igou.systems:6443}" ]] || {
    echo 'Unexpected cluster; set EXPECTED_SERVER explicitly for another demo cluster.' >&2; exit 2;
  }
}
bootstrap() {
  # Inspect usernames only; never read Kubernetes Secrets.
  local users
  users=$(oc -n "$namespace" exec deploy/forgejo-demo -- forgejo --config /var/lib/gitea/custom/conf/app.ini admin user list)
  if ! printf '%s\n' "$users" | awk '{print $2}' | grep -qx demo-admin; then
    oc -n "$namespace" exec deploy/forgejo-demo -- forgejo --config /var/lib/gitea/custom/conf/app.ini admin user create --username demo-admin --email admin@example.test --password demo-admin --admin --must-change-password=false >/dev/null
  else
    oc -n "$namespace" exec deploy/forgejo-demo -- forgejo --config /var/lib/gitea/custom/conf/app.ini admin user change-password --username demo-admin --password demo-admin --must-change-password=false >/dev/null
  fi
  if [[ ! -s $state/admin-token ]]; then
    oc -n "$namespace" exec deploy/forgejo-demo -- forgejo --config /var/lib/gitea/custom/conf/app.ini admin user generate-access-token --username demo-admin --token-name "demo-bootstrap-$(date +%s)" --scopes all --raw > "$state/admin-token.tmp"
    mv "$state/admin-token.tmp" "$state/admin-token"
  fi
}
seed() {
  bootstrap
  FORGEJO_TOKEN=$(cat "$state/admin-token")
  export FORGEJO_TOKEN
  "$root/scripts/seed.sh"
  if [[ ! -s $state/agent-token ]]; then
    oc -n "$namespace" exec deploy/forgejo-demo -- forgejo --config /var/lib/gitea/custom/conf/app.ini admin user generate-access-token --username demo-agent --token-name demo-agent --scopes write:repository,write:issue,read:user --raw > "$state/agent-token.tmp"
    mv "$state/agent-token.tmp" "$state/agent-token"
  fi
}
case ${1:-help} in
  deploy)
    cluster
    kustomize build "$root/manifests" | oc apply -f -
    oc -n "$namespace" rollout status deploy/forgejo-demo --timeout=300s
    bootstrap
    echo "Ready at $FORGEJO_URL; credentials in $state (mode 600)."
    ;;
  seed) cluster; seed ;;
  reset)
    [[ ${2:-} == --confirm-forgejo-demo ]] || { echo 'Usage: demo.sh reset --confirm-forgejo-demo (erases demo data)' >&2; exit 2; }
    COLLECTION_SOURCE=${COLLECTION_SOURCE:-$root/fixtures/collection}
    export COLLECTION_SOURCE
    [[ -f $COLLECTION_SOURCE/galaxy.yml ]] || exit 2
    cluster
    [[ $(oc get namespace "$namespace" -o jsonpath='{.metadata.labels.app\.kubernetes\.io/part-of}') == forgejo-demo ]] || exit 2
    oc -n "$namespace" scale deploy/forgejo-demo --replicas=0
    oc -n "$namespace" wait --for=delete pod -l app=forgejo-demo --timeout=180s
    oc -n "$namespace" delete pvc forgejo-demo --wait=true --timeout=180s
    rm -f "$state/admin-token" "$state/admin-token.tmp" "$state/agent-token" "$state/agent-token.tmp"
    kustomize build "$root/manifests" | oc apply -f -
    oc -n "$namespace" rollout status deploy/forgejo-demo --timeout=300s
    seed
    ;;
  *) echo 'Usage: demo.sh deploy | seed | reset --confirm-forgejo-demo' ;;
esac
