---
name: tenant-onboarding
description: Onboard a tenant to the OCP cluster — a Pipelines-as-Code CI tenant (Forgejo repo -> ci-<name> namespace) or a remote-access tenant (tailnet human -> locked-down namespace). Appends an entry to the right clusters/ocp/*-tenants/values.yaml, verifies referenced 1Password items, validates the Helm render, and opens a PR.
argument-hint: pac <owner/repo> [--profile ...] | remote <name> --members a@b.com[,c@d.com] [--role view]
allowed-tools: Read, Edit, Bash(git *), Bash(gh-app *), Bash(ghapp *), Bash(kustomize build *), Bash(helm *), Bash(yamllint *), Bash(kubeconform *), Bash(op item get *), Bash(oc get *), Bash(curl *), Bash(jq *), Bash(ls *), Bash(cat *)
---

# Onboard a tenant

## 1. Two tenant types

| Type | Chart | Values file | ArgoCD app | Namespace | What it gives |
|---|---|---|---|---|---|
| `pac` | `.helm/charts/pac-tenant` | `clusters/ocp/pac-tenants/values.yaml` | `pac-tenants` (wave 20) | `ci-<name>` | A Forgejo repo gets a Tekton / Pipelines-as-Code CI namespace |
| `remote` | `.helm/charts/remote-tenant` | `clusters/ocp/remote-tenants/values.yaml` | `remote-tenants` (wave 20) | `<name>` (`namespacePrefix` is `""`) | A tailnet human gets a locked-down namespace |

Both are **list-appends to a single existing values file** that one ArgoCD
Application renders for the whole fleet. That is why this is a skill and not an
RHDH scaffolder template: the scaffolder can only create new files, never modify
existing ones, so there is nothing for `fetch:template` to write.

## 2. Argument parsing

The first positional token is the type — `pac` or `remote`. Refuse anything
else; do not guess.

**`pac`** — second token is `<owner>/<repo>` or a full
`https://forgejo.apps.ocp.igou.systems/<owner>/<repo>` URL. Derive `<name>` from
the last path segment, lowercased, with every non-`[a-z0-9-]` character replaced
by `-`. **Confirm the derived name with the user** before writing anything.

| Flag | Meaning | Default |
|---|---|---|
| `--profile simple\|with-deps\|container-builder` | Entry shape (see step 3) | `simple` |
| `--gitProviderKey <key>` | Remote key holding `provider.token` + `webhook.secret` | `ci-forgejo-<name>` |
| `--imageStream name:image:tag` | Repeatable. ImageStream importing an upstream base image | — |
| `--imagePullSecret name:key[:store]` | Repeatable. Pull-only docker secret | — |
| `--serviceAccountSecret name:key[:asImagePullSecret][:store]` | Repeatable. Push creds on the `pipeline` SA | — |
| `--workspaceSecret name:key[:store]` | Repeatable. Opaque secret, all fields projected as-is | — |

**`remote`** — second token is `<name>`, which must match `^[a-z0-9-]+$`.

| Flag | Meaning | Default |
|---|---|---|
| `--members a@b,c@d` | **Required.** Comma-separated tailnet identities — this is what makes the NOTES grant block copy-pasteable | — |
| `--role remote-tenant-operator\|edit\|view` | ClusterRole bound to the impersonated group | `remote-tenant-operator` |
| `--psa restricted\|baseline\|privileged` | PSA enforce level | `restricted` |
| `--grantGroup <group>` | Group the Tailscale proxy impersonates | `<name>-operator` |
| `--allow-monitoring` | Add the allow-from-monitoring NetworkPolicy | off |
| `--extra-egress name:cidr:port/proto` | Repeatable additive egress NetworkPolicy | — |

**Global** — `--cluster ocp` (default; only `ocp` has tenant charts today) and
`--no-pr` (stop after validation, leave the working tree dirty for review).

## 3. Step 1 — read current state

1. Read the chart values (`.helm/charts/<chart>/values.yaml`). Its schema
   comment block is authoritative for field names and defaults — read it, do not
   work from memory.
2. Read the cluster values file (`clusters/ocp/<type>-tenants/values.yaml`).
3. If a tenant with that name already exists, **ABORT**:
   `Tenant <name> already exists at line N — edit it directly`. Never silently
   merge into an existing entry.
4. `tenants:` is kept alphabetically ordered by `name` for stable diffs. Note
   the insertion point now.

## 4. Step 2 — pre-flight (type-specific)

### pac

**(a) Verify the Forgejo repo exists.** Refuse to proceed if this fails:

```bash
curl -fsSL https://forgejo.apps.ocp.igou.systems/api/v1/repos/<owner>/<repo> \
  | jq -r '.full_name, .private'
```

**(b) Verify every remote secret key** the entry will contain — the gitProvider
key plus each imagePull / serviceAccount / workspace secret:

```bash
bash .claude/skills/tenant-onboarding/scripts/verify-remote-secret.sh <clustersecretstore> <key>
```

The store is the file-level `secretStore.name` (`onepassword-ocp-pull`); a
per-secret `secretStore.name` overrides it. Report a table:

| key | store | vault | FOUND/MISSING | field labels |

On **MISSING**, offer the same three-way choice as `add-externalsecret` step 3b:
proceed anyway (the ExternalSecret will not sync until the item exists) /
re-enter the key / abort. Never skip past a MISSING silently.

Cross-check expected fields and **warn** on a mismatch (a warning, not a
blocker — the user may plan to add the field):

- gitProvider item → `provider.token` and `webhook.secret`
- docker secrets → `dockerconfigjson` (or whatever `dockerconfigField` names)
- workspace secrets → whatever the pipeline reads (e.g. `token` for
  `rh-automationhub-credentials`)

### remote

This chart creates no secrets, so pre-flight is cluster-shaped and **optional** —
if `oc whoami` fails, skip it cleanly with a warning rather than aborting.

- `oc get nodes -l node-role.kubernetes.io/tenant` must return at least one node
  (hpg5 / p330) or tenant pods will never schedule.
- `oc get clusterrole remote-tenant-operator` must exist when `--role` is the
  default.
- Confirm the Tailscale API-server proxy is on:
  `apiServerProxyConfig.mode: "true"` in
  `components/tailscale-operator/kustomization.yaml`.
- Validate each `--members` value looks like a tailnet identity (an email, or
  `tag:`-prefixed). It is documentation-only in the chart, but it becomes the
  grant's `src`.

## 5. Step 3 — build the entry

Block style only, 2-space indent, no flow mappings (lab convention). Add a short
`#` comment on any non-obvious field — mirror how the `igou-ansible` entry
annotates its per-secret `secretStore` overrides with
`# Item lives in the <vault> context vault.`

### pac — minimal entry

```yaml
  - name: <name>
    url: https://forgejo.apps.ocp.igou.systems/<owner>/<repo>
    gitProvider:
      remoteRef:
        key: ci-forgejo-<name>
```

Then per profile:

| Profile | Adds |
|---|---|
| `simple` | nothing else |
| `with-deps` | `secrets.imagePullSecrets` and/or `secrets.workspaceSecrets` |
| `container-builder` | `imageStreams`, `secrets.serviceAccountSecrets` (with `asImagePullSecret: true` for a robot that both pulls and pushes), **and** the mandatory `extraEgress` trio below |

```yaml
    extraEgress:
      # Buildah pulls the FROM base image from the in-cluster registry SVC.
      - name: allow-internal-registry
        namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: openshift-image-registry
        ports:
          - port: 5000
            protocol: TCP
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

Why the CIDR form: `allow-external-egress` excepts 10.0.0.0/8, and the apps
router runs hostNetwork so a `namespaceSelector` can never match it.

**Do NOT auto-add `params:`.** Galaxy / Automation Hub wiring is deliberately
per-tenant; point the user at the `igou-ansible` entry as the reference.

Whenever any `secrets:` block is added, print this verbatim:

> This tenant has secrets — the chart collapses ok_to_test to the pullRequest
> allowlist. New reviewers require a git commit, not a /ok-to-test comment.

### remote — minimal entry

```yaml
  - name: <name>
    members: ["alice@example.com"]
    # role: view
```

Add `role` / `psa` / `grantGroup` / `allowMonitoring` / `extraEgress` only when
the matching flag was passed.

## 6. Step 4 — append with Edit, never yq

Use the **Edit** tool against a unique anchor: the last existing entry's
trailing line, or the literal `tenants: []`. A `yq` or full-file round-trip
would relocate or drop the ~90 lines of schema comments these files carry.

`tenants: []` must become `tenants:` on its own line followed by the entry —
appending under a literal `[]` is invalid YAML.

Keep `tenants:` alphabetically ordered by `name`.

## 7. Step 5 — validate

From the repo root:

```bash
bash .claude/skills/tenant-onboarding/scripts/validate-tenants.sh <pac|remote>
```

It runs yamllint, `kustomize build --enable-helm`, kubeconform, and prints the
chart NOTES.

If anything fails, **revert the Edit and report**. Never leave a broken
values.yaml: one malformed entry fails the render for the ENTIRE fleet and halts
the ArgoCD sync of every other tenant.

## 8. Step 6 — PR

Only after validation is green and `--no-pr` was not passed.

```bash
git -C /workspace/igou-openshift fetch origin main
git -C /workspace/igou-openshift worktree add -b rollout/tenant-<type>-<name> \
  /workspace/scratch/tenant-<name> origin/main
# re-apply the Edit in the worktree, re-run validate-tenants.sh there
git -C <worktree> add clusters/ocp/<type>-tenants/values.yaml
git -C <worktree> commit -m "feat(<type>-tenants): onboard <name>"
git -C <worktree> push -u origin rollout/tenant-<type>-<name>
gh-app --repo igou-io/igou-openshift -- pr create -R igou-io/igou-openshift \
  --base main --head rollout/tenant-<type>-<name> \
  --title "feat(<type>-tenants): onboard <name>" --body-file <body.md>
```

**NEVER `git checkout -b` in /workspace/igou-openshift** — it is a shared
checkout parked on another agent's branch, with sibling worktrees. Always
`git worktree add`.

Never bare `gh`; never a PAT (see the `github-auth` skill). Pushing over HTTPS
works via the ghapp credential helper with no token handling.

## 9. Step 7 — PR body / completion report

The body MUST carry the manual follow-ups — nothing downstream does them.

**Both types.** After merge, ArgoCD auto-syncs the `<type>-tenants` Application
(selfHeal on, prune OFF — so offboarding later needs a manual prune).

**remote.**

1. Paste the grant JSON block printed by the chart NOTES into the Tailscale
   admin console → Access controls → the `grants` array. `impersonate.groups`
   MUST equal `grantGroup` (default `<name>-operator`), or the user
   authenticates and is then Forbidden on everything.
2. The user runs `tailscale up`, then
   `tailscale configure kubeconfig tailscale-operator`, then
   `oc config set-context --current --namespace=<name>`.
3. `oc project <ns>` fails by design — the role cannot read Project objects.
   Point at `docs/remote-tenant-access/README.md`.

**pac.**

1. Create the Forgejo webhook by hand:
   `https://forgejo.apps.ocp.igou.systems/<owner>/<repo>/settings/hooks` → Add
   Webhook → Forgejo. Target URL from
   `oc get route -n openshift-pipelines pipelines-as-code-controller -o jsonpath='https://{.spec.host}'`;
   method POST, content type `application/json`; Secret = the `webhook.secret`
   field of the 1Password item; events Push, PR Opened / Reopened /
   Synchronized / Label updated / Closed, Issue Comment.
2. Any 1Password item reported MISSING must be created with the listed fields.
3. The repo needs a `.tekton/*.yaml` PipelineRun before anything runs.
4. `container-builder` only: wire `params:` for Galaxy / Automation Hub if the
   build pulls collections.
5. Reprint the okToTest-collapse note if secrets were added.

## 10. Common pitfalls

- **Missing `extraEgress` on a container-builder tenant** → Quay push and
  Forgejo clone hang. `allow-external-egress` excepts 10.0.0.0/8 and the apps
  router runs hostNetwork, so only a `cidr: 10.10.9.10/32` rule works. There is
  no chart default.
- **`pushSecrets:`** → renamed to `serviceAccountSecrets:` (it collided with the
  ESO `PushSecret` CRD). Old-shape values are a hard render failure.
- **`onepasswordItem:`** → renamed to `remoteRef.key:` for provider neutrality.
  Also a hard render failure.
- **Missing `gitProvider.remoteRef.key`** → explicit `fail()`; there is no
  chart-level default.
- **Trying to widen `okToTest` on a secret-bearing tenant** → the chart silently
  collapses it to `pullRequest`. Add reviewers by commit.
- **Grant-group drift on the remote side** → grant `impersonate.groups` !=
  `grantGroup` gives a successful `oc whoami` and Forbidden on everything.
- **Editing the shared checkout instead of a worktree** → hijacks another
  agent's branch. Always `git worktree add`.
- **`dockerconfigField:` on a secret whose source field already IS
  `dockerconfigjson`** → harmless but redundant; leave it off.
