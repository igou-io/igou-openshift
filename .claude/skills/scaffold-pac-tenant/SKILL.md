---
name: scaffold-pac-tenant
description: Use when onboarding a new Forgejo repo to Pipelines-as-Code on this cluster — adding an entry to clusters/ocp/pac-tenants/values.yaml, wiring Tekton container-build pipelines, or extending CI access for a new project.
argument-hint: <forgejo-url-or-owner/repo> [--profile simple|with-deps|container-builder] [--imagePullSecret name:remote-key] [--serviceAccountSecret name:remote-key[:asImagePullSecret]] [--workspaceSecret name:remote-key] [--imageStream name:upstream-image] [--gitProviderKey <remote-key>]
disable-model-invocation: true
allowed-tools: Read, Edit, Bash(curl *), Bash(yq *), Bash(helm template *), Bash(kubeconform *), Bash(grep *), Bash(cat *), Bash(ls *), Bash(git diff *), Bash(make test)
---

# Scaffold a PaC tenant

Add one tenant entry to `clusters/ocp/pac-tenants/values.yaml`. The entry will be picked up by ArgoCD on next sync of the `pac-tenants` Application.

The chart (`.helm/charts/pac-tenant/`) is intentionally ESO-provider-neutral — every secret reference goes through `remoteRef: {key, property?, version?}` and the chart-level `secretStore: {kind, name}` resolves to whichever ClusterSecretStore the cluster has configured (currently `onepassword-sdk-ocp-pull`). Do not introduce 1Password-specific field names.

Forgejo instance: `https://forgejo.apps.ocp.igou.systems` (read from `.helm/charts/pac-tenant/values.yaml`'s `forgejo.url`).

## Profiles

Pick a profile based on what the pipeline will do. Profiles compose with explicit flags — flags override / extend profile defaults.

| Profile | Use when | What it wires |
|---|---|---|
| `simple` (default) | Pure CI: lint, test, validate. No image builds, no private deps. | Tenant entry with `gitProvider` only. |
| `with-deps` | CI needs private base images or third-party tokens (Snyk, Codecov, npm registry...). | Adds `secrets.imagePullSecrets` and/or `secrets.workspaceSecrets`. |
| `container-builder` | Pipeline builds & pushes container images (ansible-builder, Buildah, etc.). | Adds `imageStreams`, `serviceAccountSecrets` with `asImagePullSecret: true` for the registry robot, AND `extraEgress` for the cluster apps router so Quay push + Forgejo clone work (default-deny blocks 10.0.0.0/8). |

## Parsing arguments

`$ARGUMENTS` may contain:
- A Forgejo URL (`https://forgejo.apps.ocp.igou.systems/<owner>/<repo>`) or `<owner>/<repo>` shorthand. **Required.**
- `--profile simple|with-deps|container-builder` — defaults to `simple`.
- `--gitProviderKey <remote-key>` — overrides default `ci-forgejo-<name>` for the Forgejo PAT + webhook secret.
- `--imagePullSecret <name>:<remote-key>` — repeatable. Pull-only docker secret on `pipeline-sa.imagePullSecrets`.
- `--serviceAccountSecret <name>:<remote-key>[:asImagePullSecret]` — repeatable. Docker secret on `pipeline-sa.secrets` (Tekton cred-helper reads it for `buildah push`). Trailing `:asImagePullSecret` ALSO attaches to `imagePullSecrets` (use for robot accounts that both pull and push).
- `--workspaceSecret <name>:<remote-key>` — repeatable. Opaque secret, referenced from PipelineRun workspaces or from Repository.params `secret_ref`.
- `--imageStream <name>:<upstream-image-with-tag>` — repeatable. Creates an OpenShift ImageStream importing the upstream image. Required for ansible-builder base images.

Examples:
- `igou-io/llmkube` — simple tenant.
- `igou-io/api --profile with-deps --imagePullSecret ghcr-readonly:ci-ghcr-readonly --workspaceSecret snyk:ci-snyk-org`
- `igou-io/igou-ansible --profile container-builder --imageStream ee-minimal-rhel9:registry.redhat.io/ansible-automation-platform-26/ee-minimal-rhel9:latest --serviceAccountSecret quay-push-config:ci-quay-shared:asImagePullSecret`

## Step 1: Resolve repo

If the input is a shorthand `owner/repo`, expand to `https://forgejo.apps.ocp.igou.systems/owner/repo`.

Derive `<tenant-name>` from the repo path (last segment of the URL, lowercase, with non-`[a-z0-9-]` characters replaced by `-`). Confirm the derived name with the user before proceeding.

Verify the repo exists:
```bash
curl -fsSL https://forgejo.apps.ocp.igou.systems/api/v1/repos/<owner>/<repo> | yq -p=json -o=yaml '.full_name, .private'
```
Refuse to proceed if the command fails (repo doesn't exist or isn't reachable).

## Step 2: Check existing values.yaml

Read `clusters/ocp/pac-tenants/values.yaml`. If a tenant with the derived name already exists under `tenants:`, abort with: "Tenant `<name>` is already defined at line <N> — use Edit to modify it."

## Step 3: Build the new entry

Always include the minimum required fields:
```yaml
- name: <tenant-name>
  url: <full-https-forgejo-url>
  gitProvider:
    remoteRef:
      key: <gitProviderKey or ci-forgejo-<name>>
```

Then add profile-specific blocks:

### `simple` — nothing else.

### `with-deps`
```yaml
  secrets:
    imagePullSecrets:                        # for --imagePullSecret flags
      - name: <secret-name>
        remoteRef:
          key: <remote-key>
    workspaceSecrets:                        # for --workspaceSecret flags
      - name: <secret-name>
        remoteRef:
          key: <remote-key>
```

### `container-builder`
```yaml
  imageStreams:                              # for --imageStream flags
    - name: <stream-name>
      from: <upstream-image:tag>
  secrets:
    serviceAccountSecrets:                   # for --serviceAccountSecret flags
      - name: <secret-name>
        remoteRef:
          key: <remote-key>
        asImagePullSecret: true              # if the flag had :asImagePullSecret
    # workspaceSecrets and imagePullSecrets if passed
  # REQUIRED for container-builder: tenant pipelines push to internal Quay and
  # clone from internal Forgejo, both of which go through the cluster apps
  # router (10.10.9.10:443). Default allow-external-egress excepts 10.0.0.0/8.
  extraEgress:
    - name: allow-quay-push
      cidr: 10.10.9.10/32
      ports:
        - port: 443
          protocol: TCP
    - name: allow-forgejo-clone
      cidr: 10.10.9.10/32
      ports:
        - port: 443
          protocol: TCP
```

**Tell the user explicitly** when any `secrets:` block is added: "This tenant has secrets — `okToTest` will be auto-collapsed to the `pullRequest` allowlist by the chart. Adding contributors will require a kustomization commit, not a PR comment."

**Do NOT auto-add `params:`** for Hub/Galaxy config. Repository.params for ansible-builder Galaxy server config (rh_certified, validated, community URLs + tokens) is intentionally per-tenant — the user wires those manually once they know which Galaxy scopes the build needs. Mention this in the completion report if the profile is `container-builder`.

## Step 4: Insert the entry alphabetically

The `tenants:` list should be ordered alphabetically by `name` to keep diffs stable. Insert the new entry at the correct position.

If the list is currently empty (`tenants: []`), replace with `tenants:` on its own line followed by the new entry.

## Step 5: Validate

Run from the repo root:
```bash
helm template pac-tenants .helm/charts/pac-tenant/ -f clusters/ocp/pac-tenants/values.yaml > /tmp/pac-render.yaml
echo "Rendered $(grep -c '^kind:' /tmp/pac-render.yaml) resources"
kubeconform -strict -ignore-missing-schemas -summary /tmp/pac-render.yaml
make test
```

If any check fails, abort and report the errors. Do not leave a broken values.yaml in place; revert the edit.

## Step 6: Report completion

Print to the user:

1. **Path of the file modified** + `git diff` of the change.

2. **Webhook setup checklist** for the target Forgejo repo (PaC has no CLI helper for Forgejo, so this is manual):
   1. Go to `https://forgejo.apps.ocp.igou.systems/<owner>/<repo>/settings/hooks` → **Add Webhook** → **Forgejo**.
   2. Target URL: get with `oc get route -n openshift-pipelines pipelines-as-code-controller -o jsonpath='https://{.spec.host}'`.
   3. HTTP method `POST`, content type `application/json`.
   4. Secret: same value stored in remote secret `<gitProviderKey>` under field `webhook.secret`. Must be non-empty (PaC validates HMAC-SHA256).
   5. Custom events — tick: **Push**, **PR Opened / Reopened / Synchronized / Label updated / Closed**, **Issue Comment**.
   6. Save the webhook.

3. **Remote secret checklist** — every `remoteRef.key` you wrote must exist in the secret store backing `secretStore.name` in `clusters/ocp/pac-tenants/values.yaml`, with the fields below. Print one entry per secret you added:

| Secret type | Required fields on the remote secret |
|---|---|
| `gitProvider` (Forgejo) | `provider.token` (Forgejo PAT with `repository:write`+`issue:write`, optionally `organization:read`); `webhook.secret` (HMAC secret matching the Forgejo webhook config) |
| `imagePullSecrets[]`, `serviceAccountSecrets[]` | `dockerconfigjson` (full docker config JSON, base64-decoded) — or whatever name you set via optional per-secret `dockerconfigField:` |
| `workspaceSecrets[]` | Any fields the pipeline needs; all remote fields are projected as-is into an Opaque K8s Secret |

4. **For `container-builder` profile**, also remind the user: "If this pipeline needs collections from RH Automation Hub or another Galaxy server, add Repository.params manually under the tenant — see `.helm/charts/pac-tenant/values.yaml` schema, or the igou-ansible tenant as a reference. Hub credentials need an additional `workspaceSecret` (e.g. `rh-automationhub-credentials` with field `token`)."

5. **"User must review and commit. Skill does not auto-commit."**

## Common pitfalls

- **Forgot extraEgress for a container-builder tenant** → pipeline times out on Quay push / Forgejo clone. The default `allow-external-egress` NetworkPolicy excepts `10.0.0.0/8`, which includes the apps router. The chart does NOT add this by default — it's per-tenant opt-in.
- **Used `pushSecrets:` instead of `serviceAccountSecrets:`** → chart no longer accepts that field; it was renamed because it collided with the ESO `PushSecret` CRD term.
- **Used `onepasswordItem:` instead of `remoteRef.key:`** → chart now rejects this; schema is provider-neutral.
- **Forgot to provide `gitProvider.remoteRef.key`** → render fails with explicit `fail()` message. There's no chart-level default; every tenant must specify the key.
- **Added `dockerconfigField:` for a secret whose source actually IS `dockerconfigjson`** → harmless but redundant; leave it off.
- **Tried to widen `okToTest` after adding secrets** → chart silently collapses `okToTest` to `pullRequest` whenever any secrets exist. Adding new reviewers requires an explicit pullRequest list edit, not a `/ok-to-test` PR comment.
