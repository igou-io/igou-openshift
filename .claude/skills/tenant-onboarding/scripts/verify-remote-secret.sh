#!/usr/bin/env bash
#
# verify-remote-secret.sh — check that a remoteRef.key exists in the 1Password
# vault backing a ClusterSecretStore, and report its field LABELS only.
#
# SAFETY — read before editing:
#   * `op item get --format json` returns CONCEALED field VALUES in cleartext.
#     Raw `op` output must NEVER reach stdout, a file, a log, or a PR body.
#     Everything goes through `jq -r '[.fields[].label] | join(", ")'`.
#   * Never `--reveal`. Never `op read`. Never echo raw `op` output.
#   * In this devcontainer `op` runs in Connect mode (OP_CONNECT_HOST /
#     OP_CONNECT_TOKEN): `op vault list` hard-errors and `.vault.name` in item
#     JSON is empty (only the vault ID is populated). Resolve vaults from the
#     ClusterSecretStore or the fallback map below — never by listing.
#
# Usage: verify-remote-secret.sh <clustersecretstore> <remote-key>
# Exit:  0 = item found, 1 = item missing, 2 = vault could not be resolved.

set -uo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $(basename "$0") <clustersecretstore> <remote-key>" >&2
  exit 2
fi

store="$1"
key="$2"

# The live stores use the CLASSIC `onepassword` provider, whose vaults field is
# a MAP of vault-name -> priority. It is NOT `.spec.provider.onepasswordSDK.vault`
# (the add-externalsecret skill's prose is stale); copying that jsonpath yields
# an empty vault and a false MISSING.
vault=$(oc get clustersecretstore "$store" \
  -o jsonpath='{.spec.provider.onepassword.vaults}' 2>/dev/null \
  | jq -r 'keys[0] // empty' 2>/dev/null)

if [[ -z "$vault" ]]; then
  # No cluster access (or an unexpected provider shape) — fall back to the
  # verified store -> vault map.
  case "$store" in
    onepassword-ocp-pull) vault=ocp-pull ;;
    onepassword-ocp-push) vault=ocp-push ;;
    onepassword-claude) vault=claude ;;
    onepassword-lab-forgejo) vault=lab_forgejo ;;
    onepassword-lab-container-registries) vault=lab_container_registries ;;
    onepassword-lab-redhat) vault=lab_redhat ;;
    onepassword-lab-openshift) vault=lab_openshift ;;
    onepassword-lab-github) vault=lab_github ;;
    onepassword-lab-external-api-keys) vault=lab_external_api_keys ;;
    onepassword-lab-s3) vault=lab_s3 ;;
    onepassword-lab-aap) vault=lab_aap ;;
    onepassword-lab-routeros) vault=lab_routeros ;;
    onepassword-lab-serviceaccounts) vault=lab_serviceaccounts ;;
    *)
      echo "WARNING  could not resolve a vault for store $store (not in cluster, not in fallback map)" >&2
      exit 2
      ;;
  esac
fi

# Capture op's exit code directly. A pipeline would report the LAST command's
# status (e.g. `op item get <missing> | head` exits 0), masking the failure.
if ! op item get "$key" --vault "$vault" --format json >/dev/null 2>&1; then
  echo "MISSING  $key  (vault $vault, store $store)"
  exit 1
fi

labels=$(op item get "$key" --vault "$vault" --format json 2>/dev/null \
  | jq -r '[.fields[].label] | join(", ")')
echo "FOUND    $key  (vault $vault)  fields: $labels"
