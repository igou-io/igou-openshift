---
name: scaffold-pac-tenant
description: Add a new PaC tenant entry to clusters/ocp/pac-tenants/values.yaml. Verifies the Forgejo repo exists, derives a name from the URL, applies defaults, supports optional --imagePullSecret and --workspaceSecret flags. Validates the rendered chart with helm template + kubeconform before reporting completion. Does NOT commit — user reviews diffs first.
argument-hint: <forgejo-url-or-owner/repo> [--imagePullSecret name:remote-key] [--workspaceSecret name:remote-key ...] [--gitProviderKey <remote-key>]
disable-model-invocation: true
allowed-tools: Read, Edit, Bash(curl *), Bash(yq *), Bash(helm template *), Bash(kubeconform *), Bash(grep *), Bash(cat *), Bash(ls *), Bash(git diff *)
---

# Scaffold a PaC tenant

Add one tenant entry to `clusters/ocp/pac-tenants/values.yaml`. The entry will be picked up by ArgoCD on next sync of the `pac-tenants` Application.

Forgejo instance: `https://forgejo.apps.ocp.igou.systems` (read from `.helm/charts/pac-tenant/values.yaml`'s `forgejo.url`).

## Parsing arguments

`$ARGUMENTS` may contain:
- A Forgejo URL (`https://forgejo.apps.ocp.igou.systems/<owner>/<repo>`) or `<owner>/<repo>` shorthand. Required.
- Zero or more `--imagePullSecret <name>:<remote-key>` flags. The remote key is the lookup key in the configured ESO secret store (e.g. 1Password item name, Vault path, AWS secret ID).
- Zero or more `--workspaceSecret <name>:<remote-key>` flags.
- Optional `--gitProviderKey <remote-key>` — the remote key for the per-tenant Forgejo PAT + webhook secret. Defaults to `ci-forgejo-<name>`.

Examples:
- `https://forgejo.apps.ocp.igou.systems/igou-io/igou-openshift`
- `igou-io/llmkube --imagePullSecret ghcr-readonly:ci-ghcr-readonly`
- `igou-io/foo --workspaceSecret snyk:ci-snyk-org --workspaceSecret codecov:ci-codecov`

## Step 1: Resolve repo

If the input is a shorthand `owner/repo`, expand to `https://forgejo.apps.ocp.igou.systems/owner/repo`.

Derive `<tenant-name>` from the repo path (last segment of the URL, lowercase, with non-`[a-z0-9-]` characters replaced by `-`). Confirm the derived name with the user before proceeding.

Verify the repo exists. Forgejo's API is at `/api/v1/repos/<owner>/<repo>`. Auth uses the cluster admin's PAT if available; for a public-anonymous check use:
```bash
curl -fsSL https://forgejo.apps.ocp.igou.systems/api/v1/repos/<owner>/<repo> | yq -p=json -o=yaml '.full_name, .private'
```
Refuse to proceed if the command fails (the repo doesn't exist or isn't reachable).

## Step 2: Check existing values.yaml

Read `clusters/ocp/pac-tenants/values.yaml`. If a tenant with the derived name already exists under `tenants:`, abort with a clear error: "Tenant `<name>` is already defined at line <N> — use Edit to modify it."

## Step 3: Build the new entry

Construct the entry. Minimum:
```yaml
- name: <tenant-name>
  url: <full-https-forgejo-url>
  gitProvider:
    remoteRef:
      key: <gitProviderKey>          # defaults to ci-forgejo-<name>
```

Default the `gitProvider.remoteRef.key` to `ci-forgejo-<name>` if `--gitProviderKey` was not supplied. The chart itself requires this field — there is no auto-default at the chart level.

If `--imagePullSecret name:remote-key` flags were passed, add a `secrets.imagePullSecrets:` list using the per-secret shape:
```yaml
secrets:
  imagePullSecrets:
    - name: <secret-name>
      remoteRef:
        key: <remote-key>
```

If `--workspaceSecret` flags, use the same shape under `secrets.workspaceSecrets:`.

Tell the user explicitly: "This tenant has secrets — `okToTest` will be auto-collapsed to the `pullRequest` allowlist by the chart. Adding contributors will require a kustomization commit, not a PR comment."

## Step 4: Insert the entry alphabetically

Edit `clusters/ocp/pac-tenants/values.yaml`. The `tenants:` list should be ordered alphabetically by `name` to keep diffs stable. Insert the new entry at the correct position.

If the list is currently empty (`tenants: []`), replace with `tenants:` on its own line followed by the new entry.

## Step 5: Validate the rendered chart

Run from the repo root:
```bash
helm template pac-tenants .helm/charts/pac-tenant/ -f clusters/ocp/pac-tenants/values.yaml > /tmp/pac-render.yaml
echo "Rendered $(grep -c '^kind:' /tmp/pac-render.yaml) resources"
kubeconform -strict -ignore-missing-schemas -summary /tmp/pac-render.yaml
```

If kubeconform reports any Invalid resources, abort and report the errors. Do not leave a broken values.yaml in place; revert the edit.

## Step 6: Report completion

Print to the user:
- Path of the file modified.
- Diff of the change (use `git diff` on the file).
- A **webhook setup checklist** for the target Forgejo repo (PaC has no CLI helper for Forgejo, so this is manual):
  1. Go to `https://forgejo.apps.ocp.igou.systems/<owner>/<repo>/settings/hooks` → **Add Webhook** → **Forgejo**.
  2. Target URL: the public/in-cluster URL of the PaC controller. Get it with:
     ```
     oc get route -n openshift-pipelines pipelines-as-code-controller -o jsonpath='https://{.spec.host}'
     ```
  3. HTTP method `POST`, content type `application/json`.
  4. Secret: same value stored in the remote-store secret `<gitProviderKey>` under field `webhook.secret`. Must be non-empty (PaC validates HMAC-SHA256).
  5. Custom events — tick: **Push**, **PR Opened / Reopened / Synchronized / Label updated / Closed**, **Issue Comment** (PaC only acts on comments on open PRs).
  6. Save the webhook.
- A **secret store reminder**: the remote secret keyed `<gitProviderKey>` (default `ci-forgejo-<name>`) must exist in whichever ESO store backs `secretStore.name` in `clusters/ocp/pac-tenants/values.yaml`, with fields:
  - `provider.token` — a Forgejo PAT with `repository:write` + `issue:write` scopes (add `organization:read` only if you'll use team-based ok-to-test policies).
  - `webhook.secret` — the same secret you typed into the Forgejo webhook form.
- "User must review and commit. Skill does not auto-commit."
