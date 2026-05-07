# gitea-mirror GitOps Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the scaffolded `applications/gitea-mirror/` Application into the `ocp` cluster's app-of-apps, fix scaffold gaps (hostname, env vars, probes, ExternalSecret), and bring the Application up `Synced` + `Healthy`.

**Architecture:** Patch the existing `bjw-s-labs/app-template` scaffold from PR #236 in place. Use repo-local skills (`add-externalsecret`, `add-probe`, `add-to-cluster`) for the file generations they cover, then a focused manual patch for the helmCharts inline values. Two commits: one prepares the manifests, one enables them in the app-of-apps.

**Tech Stack:** Kustomize, ArgoCD app-of-apps, `bjw-s-labs/app-template` v4.6.2 Helm chart, External Secrets Operator with 1Password, Prometheus blackbox-exporter, OpenShift Routes (auto-materialized from k8s Ingress).

**Spec:** `docs/superpowers/specs/2026-05-07-gitea-mirror-gitops-design.md`.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `applications/gitea-mirror/gitea-mirror-secrets-externalsecret.yaml` | Create | Pulls `GITHUB_TOKEN`, `BETTER_AUTH_SECRET`, `ENCRYPTION_SECRET` from 1Password item `gitea-mirror`. |
| `applications/gitea-mirror/gitea-mirror-probe.yaml` | Replace placeholder | Real `Probe` CR for blackbox-exporter against `https://gitea-mirror.apps.ocp.igou.systems/api/health`. |
| `applications/gitea-mirror/kustomization.yaml` | Modify | Uncomment new resources, fix hostname `sno`→`ocp`, add literal env block, add `envFrom: [secretRef]`, switch probes from TCP to HTTP `/api/health`. |
| `clusters/ocp/values.yaml` | Modify | Add `gitea-mirror` entry at sync-wave `23`, project `cluster-apps`, source `applications/gitea-mirror`. |

Two atomic commits:
1. **Prepare manifests** — all four file changes above except the values.yaml entry.
2. **Enable in app-of-apps** — only the values.yaml entry. Lets the user inspect the prepared Application before turning it on.

---

## Phase 1: Prepare manifests

### Task 1: Verify (or create) the 1Password item

**Files:** none (1Password side only).

- [ ] **Step 1: Resolve the vault from the ClusterSecretStore**

```bash
oc get clustersecretstore onepassword-sdk-ocp-pull -o jsonpath='{.spec.provider.onepasswordSDK.vault}'
```

Expected: a vault name (e.g. `homelab` or similar). Note it for the next steps.

- [ ] **Step 2: Check whether the `gitea-mirror` item already exists**

```bash
op item get gitea-mirror --vault "<vault-from-step-1>" --format json | jq '.fields[] | {label, type}'
```

If the item exists, verify it has these three field labels (case-sensitive): `GITHUB_TOKEN`, `BETTER_AUTH_SECRET`, `ENCRYPTION_SECRET`. If yes → skip to Task 2.

If the item is missing or fields are missing, continue to Step 3.

- [ ] **Step 3: Create the 1Password item with three fields**

```bash
op item create \
  --category=login \
  --title=gitea-mirror \
  --vault="<vault-from-step-1>" \
  GITHUB_TOKEN[password]="<paste GitHub PAT with repo:read scope>" \
  BETTER_AUTH_SECRET[password]="$(op item generate-password --length=48)" \
  ENCRYPTION_SECRET[password]="$(op item generate-password --length=48)"
```

If the item already exists but is missing fields, edit instead:

```bash
op item edit gitea-mirror --vault="<vault>" \
  GITHUB_TOKEN[password]="<token>" \
  BETTER_AUTH_SECRET[password]="<random>" \
  ENCRYPTION_SECRET[password]="<random>"
```

- [ ] **Step 4: Verify all three fields are now present**

```bash
op item get gitea-mirror --vault "<vault>" --format json \
  | jq -r '.fields[] | select(.type == "CONCEALED") | .label' \
  | sort
```

Expected output (order may vary):
```
BETTER_AUTH_SECRET
ENCRYPTION_SECRET
GITHUB_TOKEN
```

- [ ] **Step 5: (Separately) create the Forgejo PAT item used during UI bootstrap**

The Forgejo PAT is **not** wired into Kubernetes — it's pasted into the gitea-mirror UI on first login. Stash it in 1Password so it doesn't live in your terminal history:

```bash
op item create \
  --category=login \
  --title=gitea-mirror-forgejo-pat \
  --vault="<vault>" \
  token[password]="<paste Forgejo PAT with write:repository scope>"
```

No commit at the end of this task — 1Password state is external to the repo.

---

### Task 2: Create the ExternalSecret using the `add-externalsecret` skill

**Files:**
- Create: `applications/gitea-mirror/gitea-mirror-secrets-externalsecret.yaml`
- Modify: `applications/gitea-mirror/kustomization.yaml` (resources list — the skill patches it)

- [ ] **Step 1: Invoke the skill**

```
/add-externalsecret applications/gitea-mirror
```

When the skill prompts:

| Prompt | Value |
|--------|-------|
| `secret-name` | `gitea-mirror-secrets` |
| `namespace` | `gitea-mirror` (auto-detected) |
| `onepassword-key` | `gitea-mirror` |
| `secret-store` | `onepassword-sdk-ocp-pull` (default) |
| `sync-wave` | `0` (the default highest+1; this is the first ESO resource in the dir) |
| `skip-dry-run` | `yes` (default) |
| `use-template` | `no` (default) |

- [ ] **Step 2: Verify the file was created and matches the spec**

```bash
cat applications/gitea-mirror/gitea-mirror-secrets-externalsecret.yaml
```

Expected: an `ExternalSecret` named `gitea-mirror-secrets` in namespace `gitea-mirror`, `secretStoreRef.name: onepassword-sdk-ocp-pull`, `dataFrom: [{extract: {key: gitea-mirror, …}}]`. The skill may also add `argocd.argoproj.io/sync-wave: "0"` and `argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true` annotations — keep them.

- [ ] **Step 3: Verify kustomization.yaml resources list now references it**

```bash
grep gitea-mirror-secrets-externalsecret applications/gitea-mirror/kustomization.yaml
```

Expected:
```
  - gitea-mirror-secrets-externalsecret.yaml
```

(Must NOT be commented out.)

- [ ] **Step 4: Validate the kustomize build still parses**

```bash
kustomize build applications/gitea-mirror/ --enable-helm > /dev/null && echo OK
```

Expected: `OK`.

No commit yet — bundled with later kustomization changes.

---

### Task 3: Replace the probe placeholder using the `add-probe` skill

**Files:**
- Modify (replace): `applications/gitea-mirror/gitea-mirror-probe.yaml`
- Modify: `applications/gitea-mirror/kustomization.yaml` (resources list — the skill patches it)

- [ ] **Step 1: Invoke the skill**

```
/add-probe https://gitea-mirror.apps.ocp.igou.systems/api/health --module http_2xx --category app:gitea-mirror --tier standard
```

When the skill asks for `owner`, answer: `platform`.

- [ ] **Step 2: Verify the file was rewritten with a real Probe**

```bash
cat applications/gitea-mirror/gitea-mirror-probe.yaml
```

Expected: a `monitoring.coreos.com/v1 Probe` named `gitea-mirror-…` with:
- `labels.app.kubernetes.io/name: blackbox-exporter`
- `spec.module: http_2xx`
- `spec.prober.url: blackbox-exporter.blackbox-exporter.svc:9115`
- `spec.targets.staticConfig.static: ["https://gitea-mirror.apps.ocp.igou.systems/api/health"]`
- `spec.targets.staticConfig.labels: {tier: standard, category: gitea-mirror, owner: platform}`

If the skill leaves any of the old placeholder comments (referring to the `apps.sno.*` URL), delete them with `Edit` — they're stale.

- [ ] **Step 3: Verify kustomization.yaml resources list now references it**

```bash
grep gitea-mirror-probe applications/gitea-mirror/kustomization.yaml
```

Expected (uncommented):
```
  - gitea-mirror-probe.yaml
```

- [ ] **Step 4: Validate**

```bash
kustomize build applications/gitea-mirror/ --enable-helm > /dev/null && echo OK
```

Expected: `OK`.

No commit yet.

---

### Task 4: Patch the helmCharts inline values

This task is the heart of the change — fixing the scaffold gaps that the skills don't cover.

**Files:**
- Modify: `applications/gitea-mirror/kustomization.yaml`

- [ ] **Step 1: Read the current helmCharts block**

```bash
sed -n '/^helmCharts:/,/^[a-z]/p' applications/gitea-mirror/kustomization.yaml
```

Confirm the structure matches what the patch below expects (containers.app.env block, probes block, ingress hosts block).

- [ ] **Step 2: Replace the `env` block to add literal env vars**

Find the existing block in `applications/gitea-mirror/kustomization.yaml`:

```yaml
            env:
              NODE_ENV: production
              HOST: 0.0.0.0
              PORT: "4321"
              DATABASE_URL: file:/app/data/gitea-mirror.db
            # Once /add-externalsecret has been run, wire the resulting Secret in here, e.g.:
            # envFrom:
            #   - secretRef:
            #       name: gitea-mirror-secrets
```

Replace with:

```yaml
            env:
              NODE_ENV: production
              HOST: 0.0.0.0
              PORT: "4321"
              DATABASE_URL: file:/app/data/gitea-mirror.db
              BETTER_AUTH_URL: https://gitea-mirror.apps.ocp.igou.systems
              PUBLIC_BETTER_AUTH_URL: https://gitea-mirror.apps.ocp.igou.systems
              BETTER_AUTH_TRUSTED_ORIGINS: https://gitea-mirror.apps.ocp.igou.systems
              AUTO_IMPORT_REPOS: "true"
              SCHEDULE_ENABLED: "true"
              SCHEDULE_INTERVAL: "0 4 * * *"
              CLEANUP_DELETE_IF_NOT_IN_GITHUB: "true"
              CLEANUP_ORPHANED_REPO_ACTION: archive
              CLEANUP_DRY_RUN: "false"
            envFrom:
              - secretRef:
                  name: gitea-mirror-secrets
```

(YAML 1.2 booleans for env values must be quoted strings — env vars are always strings, and unquoted `true`/`false` in valuesInline would render as bool and fail the chart's string schema validation.)

- [ ] **Step 3: Replace the `probes` block to use HTTP `/api/health`**

Find:

```yaml
            probes:
              liveness:
                enabled: true
                type: TCP
              readiness:
                enabled: true
                type: TCP
              startup:
                enabled: true
                type: TCP
```

Replace with:

```yaml
            probes:
              liveness:
                enabled: true
                type: HTTP
                path: /api/health
                port: http
              readiness:
                enabled: true
                type: HTTP
                path: /api/health
                port: http
              startup:
                enabled: true
                type: HTTP
                path: /api/health
                port: http
                spec:
                  failureThreshold: 30
                  periodSeconds: 10
```

(The longer startup-probe budget gives the app up to 5 minutes to come up before the kubelet starts killing pods — SQLite migration on first start can take time.)

- [ ] **Step 4: Fix the ingress hostname**

Find:

```yaml
        hosts:
          - host: gitea-mirror.apps.sno.igou.systems
```

Replace with:

```yaml
        hosts:
          - host: gitea-mirror.apps.ocp.igou.systems
```

- [ ] **Step 5: Validate the kustomization still builds**

```bash
kustomize build applications/gitea-mirror/ --enable-helm > /tmp/gitea-mirror-built.yaml && echo OK
```

Expected: `OK`.

- [ ] **Step 6: Spot-check the rendered output**

```bash
grep -E '(BETTER_AUTH_URL|envFrom|/api/health|gitea-mirror.apps.ocp.igou.systems)' /tmp/gitea-mirror-built.yaml | head -20
```

Expected: lines for the new env var, an `envFrom: [secretRef]` reference to `gitea-mirror-secrets`, the HTTP probe path, and the corrected ingress hostname.

---

### Task 5: Run full validation

**Files:** none.

- [ ] **Step 1: Run yamllint**

```bash
make lint
```

Expected: no errors. (yamllint config is at the repo root.)

- [ ] **Step 2: Run kustomize-build validation across the repo**

```bash
make validate-kustomize
```

Expected: builds every kustomization.yaml without error, including `applications/gitea-mirror/`.

- [ ] **Step 3: Run kubeconform schema validation**

```bash
make validate-schemas
```

Expected: no schema errors. (External-secrets.io and monitoring.coreos.com CRD schemas are vendored under the schema-cache; the make target points kubeconform at them.)

If any step fails, fix the offending YAML and re-run from Step 1. Don't move past green.

---

### Task 6: Commit Phase 1

**Files:** all changes from Tasks 2–4.

- [ ] **Step 1: Inspect the staged diff**

```bash
git status
git diff applications/gitea-mirror/
```

Expected modifications:
- `applications/gitea-mirror/kustomization.yaml` — env block, envFrom, probes, hostname, resources list (uncommented)
- `applications/gitea-mirror/gitea-mirror-probe.yaml` — full Probe (no longer placeholder)

Expected new files:
- `applications/gitea-mirror/gitea-mirror-secrets-externalsecret.yaml`

No other changes outside `applications/gitea-mirror/`.

- [ ] **Step 2: Commit**

```bash
git add applications/gitea-mirror/
git commit -m "$(cat <<'EOF'
Wire up gitea-mirror manifests for first deploy

Fix scaffold gaps left by PR #236: correct hostname (sno → ocp),
add ExternalSecret pulling GITHUB_TOKEN / BETTER_AUTH_SECRET /
ENCRYPTION_SECRET from 1Password, switch probes to HTTP /api/health,
populate Probe CR for blackbox-exporter, and add env vars for
auto-import + scheduled sync + archive-on-orphan cleanup.

The Application is not yet wired into clusters/ocp/values.yaml; that
follows in a separate commit so the prepared manifests can be inspected
before they go live.
EOF
)"
```

- [ ] **Step 3: Verify the commit**

```bash
git log -1 --stat
```

Expected: 1 commit, ~3 files changed (1 new, 2 modified).

---

## Phase 2: Enable in app-of-apps

### Task 7: Add to `clusters/ocp/values.yaml` using the `add-to-cluster` skill

**Files:**
- Modify: `clusters/ocp/values.yaml`

- [ ] **Step 1: Invoke the skill**

```
/add-to-cluster applications/gitea-mirror ocp
```

When the skill prompts:

| Prompt | Value |
|--------|-------|
| `entry-name` | `gitea-mirror` (default) |
| `sync-wave` | `'23'` (override the default `'20'` — must be after forgejo at `'22'`) |
| `namespace` | `gitea-mirror` (matches entry-name → won't be inserted) |
| `include-namespace` | `no` (default, since namespace == entry-name) |
| `compare-options` | `yes` (default) |

- [ ] **Step 2: Verify the entry was inserted in the right place**

```bash
grep -n -A 6 '^  gitea-mirror:' clusters/ocp/values.yaml
```

Expected:
```yaml
  gitea-mirror:
    project: cluster-apps
    annotations:
      argocd.argoproj.io/compare-options: IgnoreExtraneous
      argocd.argoproj.io/sync-wave: '23'
    source:
      path: applications/gitea-mirror
```

(Note: if the skill omits `project: cluster-apps`, add it manually with `Edit` — every other user-facing app entry in this file uses it, and without it the Application falls under the default project which has different RBAC/source repo allowances.)

- [ ] **Step 3: Verify ordering — gitea-mirror comes after forgejo (wave 22) and before alertmanager-config (wave 25)**

```bash
grep -n -E '^  (forgejo|gitea-mirror|alertmanager-config):' clusters/ocp/values.yaml
```

Expected: the line numbers should be in ascending order `forgejo` → `gitea-mirror` → `alertmanager-config` (or `quay-operator` / `rhdh` which also sit at wave 22 — those are fine in any relative order to gitea-mirror, but all three of them must precede `alertmanager-config`).

---

### Task 8: Validate Phase 2

**Files:** none.

- [ ] **Step 1: Run the full test target**

```bash
make test
```

Expected: all of `make lint`, `make validate-kustomize`, `make validate-schemas` pass.

- [ ] **Step 2: Specifically render the app-of-apps for `ocp` and confirm gitea-mirror appears**

```bash
kustomize build clusters/ocp/ --enable-helm | grep -A 2 'name: gitea-mirror'
```

Expected: at least one block matching:
```
  name: gitea-mirror
  namespace: openshift-gitops
```

(That's the ArgoCD `Application` object. There should be exactly one with that name in `openshift-gitops`.)

---

### Task 9: Commit Phase 2

**Files:** `clusters/ocp/values.yaml` only.

- [ ] **Step 1: Inspect the staged diff**

```bash
git diff clusters/ocp/values.yaml
```

Expected: only the new `gitea-mirror` block added; no other changes.

- [ ] **Step 2: Commit**

```bash
git add clusters/ocp/values.yaml
git commit -m "$(cat <<'EOF'
Enable gitea-mirror Application on the ocp cluster

Adds the ArgoCD Application entry at sync-wave 23, immediately after
forgejo (wave 22) so the mirror destination is logically up first.
ArgoCD waves don't block on readiness, so if forgejo is unhealthy
gitea-mirror will still deploy and idle until the user completes the
post-deploy UI bootstrap (Forgejo destination + GitHub source
selection).
EOF
)"
```

- [ ] **Step 3: Verify the commit**

```bash
git log -2 --oneline
```

Expected: two new commits — Phase 1 manifest prep and Phase 2 enablement.

---

## Phase 3: Deploy + first-login bootstrap

These steps are **post-merge / post-sync** and produce no commits. They're documented here so the implementation isn't considered "done" until the Application is actually `Healthy`.

### Task 10: Trigger an ArgoCD sync and watch it converge

**Files:** none.

- [ ] **Step 1: Push the branch and merge it (or apply locally for testing)**

If iterating locally before merging to main:

```bash
oc apply -k clusters/ocp/
```

Otherwise, merge to `main`; the root app-of-apps will pick it up automatically.

- [ ] **Step 2: Watch the new Application appear and sync**

```bash
oc -n openshift-gitops get applications.argoproj.io gitea-mirror -w
```

Wait until both `SYNC STATUS` and `HEALTH STATUS` columns show `Synced` and `Healthy`. Ctrl-C when stable.

If it stays `OutOfSync`/`Degraded` for more than ~3 minutes, inspect:

```bash
oc -n openshift-gitops describe applications.argoproj.io gitea-mirror | tail -50
oc -n gitea-mirror get pods,events --sort-by=.lastTimestamp | tail -30
```

- [ ] **Step 3: Verify the Secret was materialized by ESO**

```bash
oc -n gitea-mirror get externalsecret gitea-mirror-secrets -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
oc -n gitea-mirror get secret gitea-mirror-secrets -o jsonpath='{.data}' | jq 'keys'
```

Expected first command: `True`.
Expected second command: a JSON array containing exactly `["BETTER_AUTH_SECRET", "ENCRYPTION_SECRET", "GITHUB_TOKEN"]` (order not guaranteed).

If keys are missing, the 1Password item field labels don't match — go back to Task 1 Step 4.

- [ ] **Step 4: Verify the pod comes up and the HTTP probe passes**

```bash
oc -n gitea-mirror get pods
oc -n gitea-mirror logs deploy/gitea-mirror --tail=40
```

Expected: a single `gitea-mirror-…` pod in `Running`, `1/1 Ready`. Logs should show the app listening on `:4321` with no auth-secret-related panics.

- [ ] **Step 5: Verify the Route is reachable**

```bash
curl -sI https://gitea-mirror.apps.ocp.igou.systems/api/health | head -3
```

Expected: `HTTP/2 200`.

- [ ] **Step 6: Verify Prometheus is scraping the blackbox probe**

In the OCP console → Observe → Metrics:

```promql
probe_success{instance="https://gitea-mirror.apps.ocp.igou.systems/api/health"}
```

Expected: `1` (with possibly a brief 0 while the pod was first starting).

---

### Task 11: First-login UI bootstrap (one-time, manual)

**Files:** none.

- [ ] **Step 1: Sign up the admin account**

Open `https://gitea-mirror.apps.ocp.igou.systems` in a browser. The first user signup becomes the admin account — pick a username and password and store them in 1Password if you'll want them later.

- [ ] **Step 2: Configure the Forgejo destination**

In the gitea-mirror UI, navigate to **Destinations** (or equivalent — exact wording may vary by version). Add a new destination:

| Field | Value |
|-------|-------|
| Type | Gitea (Forgejo speaks the Gitea API) |
| URL | `https://forgejo.apps.ocp.igou.systems` |
| Token | paste from 1Password item `gitea-mirror-forgejo-pat`, field `token` |

Save and verify the connection check passes.

- [ ] **Step 3: Configure the GitHub source**

Navigate to **Sources** (or equivalent). Add the orgs/users to mirror. `GITHUB_TOKEN` is already supplied via env, so no token paste needed — just pick what to mirror.

- [ ] **Step 4: Trigger an initial sync**

Manually trigger a sync to verify end-to-end. The cron schedule (`0 4 * * *` UTC, daily) takes over from there.

- [ ] **Step 5: Confirm a mirror landed in Forgejo**

```bash
curl -s -H "Authorization: token <forgejo-pat>" \
  "https://forgejo.apps.ocp.igou.systems/api/v1/repos/search?limit=5" | jq '.data[].full_name'
```

Expected: at least one mirrored repo appears in the list.

---

## Self-Review

**Spec coverage:** Every section of the spec maps to at least one task above:
- Architecture / file layout → Tasks 2, 3, 4 (manifest changes), Task 7 (values.yaml).
- Hostname fix → Task 4 Step 4.
- ExternalSecret → Tasks 1–2.
- Probe → Task 3.
- Container env / envFrom / probe-type changes → Task 4.
- values.yaml entry at wave 23 → Task 7.
- Validation → Tasks 5, 8.
- Bootstrap (manual) → Task 11.
- Risks/limitations — these are advisory and surfaced in commit messages and Task 11 instructions; no separate task needed.

**Placeholder scan:** none. Every step has the actual command / YAML / expected output.

**Type / name consistency:**
- ExternalSecret name `gitea-mirror-secrets` used identically in Task 2 (creation), Task 4 (envFrom reference), Task 10 (verification).
- 1Password item key `gitea-mirror` and field labels `GITHUB_TOKEN` / `BETTER_AUTH_SECRET` / `ENCRYPTION_SECRET` consistent across Tasks 1, 2, 10.
- Hostname `gitea-mirror.apps.ocp.igou.systems` used identically in Tasks 3 (Probe URL), 4 (env vars + ingress), 10 (curl verification), 11 (browser).
- Sync-wave `23` used in spec and Task 7.
- Service port name `http` used in the new probes block (Task 4 Step 3) matches the existing `service.app.ports.http` block in the same kustomization.yaml — already confirmed by reading the file.
