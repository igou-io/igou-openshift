#!/usr/bin/env bash
#
# validate-tenants.sh — one-shot gate for a tenant values edit.
#
#   1. yamllint the values file
#   2. kustomize build --enable-helm  (the load-bearing check: chart fail()
#      guards surface here)
#   3. kubeconform against the rendered output
#   4. print the chart NOTES — the manual follow-ups for the PR body
#
# Both values files are ONE ArgoCD Application each, rendering the WHOLE fleet.
# A single malformed entry fails the render and halts the sync of every other
# tenant, so a failure here must be reverted, never committed.
#
# Usage: validate-tenants.sh pac|remote [cluster]   (cluster defaults to ocp)

set -euo pipefail

type="${1:-}"
cluster="${2:-ocp}"

cd "$(git rev-parse --show-toplevel)"

case "$type" in
  pac)
    dir="clusters/$cluster/pac-tenants"
    chart=".helm/charts/pac-tenant"
    release="pac-tenants"
    ;;
  remote)
    dir="clusters/$cluster/remote-tenants"
    chart=".helm/charts/remote-tenant"
    release="remote-tenants"
    ;;
  *)
    echo "usage: $(basename "$0") pac|remote [cluster]" >&2
    exit 2
    ;;
esac

out="${TMPDIR:-/tmp}/tenants-$type.yaml"

echo "==> yamllint $dir/values.yaml"
yamllint -c .yamllint "$dir/values.yaml"

# AGENTS.md: these kustomizations use helmChart, so --enable-helm is mandatory
# and `oc apply -k` is never correct here.
echo "==> kustomize build --enable-helm $dir"
kustomize build --enable-helm "$dir" > "$out"
echo "    rendered $(grep -c '^kind:' "$out") resources -> $out"

# Canonical flags from the Makefile's KUBECONFORM_FLAGS. -ignore-missing-schemas
# keeps an offline run (the datreeio CRD catalog is fetched over the network) a
# warning instead of a false failure.
echo "==> kubeconform $out"
kubeconform \
  -strict \
  -ignore-missing-schemas \
  -skip ClusterSecretStore \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -summary \
  "$out"

# Neither kustomize nor `helm template` renders NOTES.txt, and helm v4 has no
# --notes flag. `helm install --dry-run` is client-side and works with no
# cluster reachable; KUBECONFIG=/nonexistent proves it never touches one.
echo "==> chart NOTES (manual follow-ups for the PR body)"
KUBECONFIG=/nonexistent helm install "$release" "$chart" -f "$dir/values.yaml" \
  --dry-run 2>/dev/null | sed -n '/^NOTES:/,$p'

# kustomize can leave a vendored charts/ dir behind; mirrors `make clean`.
rm -rf "$dir/charts"

echo "==> OK. If this change touched anything outside $dir, run \`make test\` for the fleet-wide checks."
