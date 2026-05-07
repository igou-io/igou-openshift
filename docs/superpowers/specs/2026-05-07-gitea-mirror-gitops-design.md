---
name: gitea-mirror GitOps onboarding
description: Wire the scaffolded gitea-mirror application into the ocp cluster app-of-apps, fix scaffold gaps, and bring the Application up green.
status: draft
date: 2026-05-07
---

# gitea-mirror GitOps onboarding

## Background

`applications/gitea-mirror/` was scaffolded by PR #236 (commit `14e0bac`) using the
`bjw-s-labs/app-template` Helm chart, but never added to
`clusters/ocp/values.yaml`. As checked in, the manifests would not produce a working
deploy: the ingress hostname is wrong, no `ExternalSecret` is wired, no env vars are
set for the upstream auth/scheduling features, and probes are placeholders.

`gitea-mirror` (upstream `RayLabsHQ/gitea-mirror`) is a one-way mirror tool that
imports repos from GitHub and pushes them into a Gitea-API-compatible target — in our
case the existing `forgejo` Application at `forgejo.apps.ocp.igou.systems`. Upstream's
documented database is SQLite; PostgreSQL is not officially supported, so we keep
SQLite on a PVC.

## Goals

- One ArgoCD `Application` named `gitea-mirror`, project `cluster-apps`, sync-wave `23`,
  syncing `applications/gitea-mirror/`.
- The Application reaches `Synced` + `Healthy` after first apply.
- A user can sign up at `https://gitea-mirror.apps.ocp.igou.systems` and complete
  manual destination/source bootstrap from the UI.
- `make test` passes.

## Non-goals

- Migrating from SQLite to CNPG/PostgreSQL.
- Automating the post-deploy UI bootstrap (Forgejo destination + GitHub source
  selection). Upstream stores these in the SQLite DB; there is no env-var path.
- Custom alerting rules. The Prometheus `Probe` plus existing alertmanager config is
  enough.
- Renovate changes. The image is already digest-pinned and Renovate manages bumps.

## Architecture

A single ArgoCD `Application` syncs `applications/gitea-mirror/`, which is a
Kustomization rendering:

- `Namespace/gitea-mirror`.
- `PersistentVolumeClaim/gitea-mirror-config` — 5 Gi, RWO, default
  StorageClass (`freenas-nvmeof-ssd-csi`).
- `ExternalSecret/gitea-mirror-secrets` — pulls from the 1Password
  ClusterSecretStore `onepassword-sdk-ocp-pull`, materializes
  `Secret/gitea-mirror-secrets` with three keys (`GITHUB_TOKEN`,
  `BETTER_AUTH_SECRET`, `ENCRYPTION_SECRET`).
- A `bjw-s-labs/app-template` Helm release (`gitea-mirror`, version `4.6.2`) which
  renders `Deployment`, `Service`, `Ingress`, and `ServiceAccount`. The OpenShift
  ingress controller materializes a `Route` from the `Ingress` automatically.
- `Probe/gitea-mirror-biscuit` — Prometheus blackbox probe of the public URL.

### Sync sequencing

`gitea-mirror` is wave `23`, immediately after `forgejo` (`22`). ArgoCD waves only
sequence Applications by start-time, not block-on-readiness; if `forgejo` is
degraded, `gitea-mirror` will deploy anyway and idle until Forgejo is reachable from
the user's first-login bootstrap. That's acceptable.

### Data flow

```
GitHub API  ──(GITHUB_TOKEN)──►  gitea-mirror  ──(Forgejo PAT, stored in
                                  (1 replica)     SQLite, configured via UI)──►  Forgejo
                                  │
                                  ▼
                       /app/data/gitea-mirror.db
                       (5 Gi PVC, freenas-nvmeof-ssd-csi)
```

The Forgejo PAT is **not** wired through Kubernetes Secrets. Upstream stores
destination credentials encrypted at rest in the SQLite DB using
`ENCRYPTION_SECRET`, and the only documented path to set it is the web UI.

## Component-level changes

### `applications/gitea-mirror/kustomization.yaml`

- Add `gitea-mirror-secrets-externalsecret.yaml` and `gitea-mirror-probe.yaml`
  to `resources`.
- Hostname: `gitea-mirror.apps.sno.igou.systems` →
  `gitea-mirror.apps.ocp.igou.systems` (the `apps.sno.*` domain is from a previous
  cluster name and does not resolve here).
- In the container's `env` block, add literals:
  - `BETTER_AUTH_URL=https://gitea-mirror.apps.ocp.igou.systems` (origin only — no path)
  - `PUBLIC_BETTER_AUTH_URL=https://gitea-mirror.apps.ocp.igou.systems`
  - `BETTER_AUTH_TRUSTED_ORIGINS=https://gitea-mirror.apps.ocp.igou.systems`
  - `AUTO_IMPORT_REPOS=true`
  - `SCHEDULE_ENABLED=true`
  - `SCHEDULE_INTERVAL=0 4 * * *`  (daily 04:00 UTC)
  - `CLEANUP_DELETE_IF_NOT_IN_GITHUB=true`
  - `CLEANUP_ORPHANED_REPO_ACTION=archive`
  - `CLEANUP_DRY_RUN=false`

  `BASE_URL` is intentionally **not** set — upstream defines it as a subpath prefix
  for reverse-proxy-under-a-subpath deployments (e.g. `/mirror`), and we serve at
  the host root.
- Add `envFrom: [secretRef: { name: gitea-mirror-secrets }]` so `GITHUB_TOKEN`,
  `BETTER_AUTH_SECRET`, `ENCRYPTION_SECRET` reach the process.
- Probes: switch all three (`liveness`, `readiness`, `startup`) from `type: TCP` to
  `type: HTTP` with `path: /api/health`, port 4321. The placeholder
  `gitea-mirror-probe.yaml` already documents `/api/health` as the upstream health
  endpoint.

### `applications/gitea-mirror/gitea-mirror-secrets-externalsecret.yaml` (new)

Pattern matches `applications/forgejo/forgejo-secrets-externalsecret.yaml`:

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: gitea-mirror-secrets
  namespace: gitea-mirror
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-sdk-ocp-pull
  target:
    name: gitea-mirror-secrets
    creationPolicy: Owner
    deletionPolicy: Retain
  dataFrom:
    - extract:
        key: gitea-mirror
        conversionStrategy: Default
        decodingStrategy: None
        metadataPolicy: None
        nullBytePolicy: Ignore
```

The 1Password item `gitea-mirror` (in the vault that
`onepassword-sdk-ocp-pull` is wired to) must contain **exactly** these three fields,
named verbatim so they map to env-var names. `dataFrom: extract` lifts every field
into the Secret and `envFrom` exposes every key as an env var — adding extra fields
would create unintended env vars on the pod.

- `GITHUB_TOKEN` — GitHub PAT with `repo` read scope on the orgs/users to mirror.
- `BETTER_AUTH_SECRET` — random 32+ byte string. `op item create … --generate-password`.
- `ENCRYPTION_SECRET` — random 32+ byte string. Same generator.

The Forgejo PAT used for the destination is **not** stored in this item. Keep it in
a separate 1Password item (e.g. `gitea-mirror-forgejo-pat`) — it's manually pasted
into the gitea-mirror UI on bootstrap, never read by Kubernetes.

### `applications/gitea-mirror/gitea-mirror-probe.yaml` (replace placeholder)

Pattern matches `applications/jellyfin/jellyfin-probe.yaml`:

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: gitea-mirror-biscuit
  labels:
    app.kubernetes.io/name: blackbox-exporter
spec:
  interval: 60s
  module: http_2xx
  prober:
    url: blackbox-exporter.blackbox-exporter.svc:9115
  targets:
    staticConfig:
      static:
        - https://gitea-mirror.apps.ocp.igou.systems/api/health
      labels:
        tier: standard
        category: gitea-mirror
        owner: platform
```

(Probe label values are user-defined classification — adjust `tier`/`owner` to match
whatever convention you settle on; `jellyfin-probe` uses `tier: critical`,
`owner: media`.)

### `applications/gitea-mirror/values-dummy.yaml`

No change. Existing kustomize-helmCharts workaround.

### `applications/gitea-mirror/gitea-mirror-config-pvc.yaml`

No change. Default StorageClass (`freenas-nvmeof-ssd-csi`) is correct.

### `applications/gitea-mirror/gitea-mirror-namespace.yaml`

No change.

### `clusters/ocp/values.yaml`

Add a new entry, immediately after `forgejo`:

```yaml
gitea-mirror:
  project: cluster-apps
  annotations:
    argocd.argoproj.io/compare-options: IgnoreExtraneous
    argocd.argoproj.io/sync-wave: '23'
  source:
    path: applications/gitea-mirror
```

The `add-to-cluster` skill picks the insertion point automatically by sync-wave
ordering.

## Bootstrap (manual, one-time, post-deploy)

Once ArgoCD reports the Application `Synced` + `Healthy`:

1. Open `https://gitea-mirror.apps.ocp.igou.systems` and create the first user —
   that user becomes admin.
2. In the gitea-mirror UI, configure the Forgejo destination:
   - URL: `https://forgejo.apps.ocp.igou.systems`
   - Token: paste from 1Password (`gitea-mirror-forgejo-pat`).
3. In the UI, configure the GitHub source: pick orgs/users to mirror.
   `GITHUB_TOKEN` is already supplied via env, so the API client is authenticated.
4. Trigger an initial sync to verify; the cron schedule (daily 04:00 UTC) takes
   over after that.

## Validation

- `make test` (`make lint`, `make validate-kustomize`, `make validate-schemas`).
- ArgoCD sync of the new `gitea-mirror` Application reaches `Synced` + `Healthy`.
- `Probe/gitea-mirror-biscuit` shows green in Prometheus once the Deployment is up.

## Risks & known limitations

- **Manual bootstrap is unavoidable.** The Forgejo destination cannot be configured
  from env or a Secret — it lives in the SQLite DB. If the PVC is wiped, this step
  has to be repeated.
- **PVC loss = session + token loss.** Wiping the PVC drops session cookies and the
  encrypted destination token. With `ENCRYPTION_SECRET` preserved in 1Password, only
  the encrypted Forgejo token is gone — sessions can be re-issued; the Forgejo PAT
  has to be re-pasted in the UI.
- **Sync wave does not gate on Forgejo readiness.** If Forgejo is down at deploy
  time, gitea-mirror will come up but be unable to push. It will retry; nothing
  destructive.
- **Image tag pinning.** `v3.15.6@sha256:…`. Upgrades are managed by Renovate.
  Out-of-band tag bumps without digest update will be reverted by ArgoCD.
- **PostgreSQL is not in scope.** If upstream later documents Postgres support and
  we want HA, that's a follow-up: drop the PVC, add a CNPG cluster, set
  `DATABASE_URL` to `postgres://…`. Not blocked by this work.
