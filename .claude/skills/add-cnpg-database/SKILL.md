---
name: add-cnpg-database
description: Add a CloudNative-PG (CNPG) PostgreSQL `Cluster` to an existing application or component. Generates the Cluster YAML with the project's defaults baked in (sync-wave -1, enablePDB:false on single-instance, freenas-nvmeof-ssd-csi storage, PodMonitor on), patches kustomization.yaml, validates, and prints the workload-side env-from-secret snippet for the auto-generated `<cluster>-app` Secret.
argument-hint: <app-or-component-path>
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(kustomize build *), Bash(ls *), Bash(cat *), Bash(oc get csv *), Bash(oc get clusters.postgresql.cnpg.io *), Bash(oc get sc *), Bash(oc explain *), Bash(make lint), Bash(make validate-kustomize)
---

# Add a CNPG-managed PostgreSQL database to a workload

Add a `postgresql.cnpg.io/v1 Cluster` resource to an existing directory under
`applications/` or `components/`, register it in `kustomization.yaml`, validate
the build, and print the env-from-secret snippet the workload needs to consume
the auto-generated `<cluster>-app` credentials Secret.

The skill bakes in conventions learned the hard way in this repo. Do **not**
strip these defaults without a stated reason — each one was added to fix a
real alert or sync issue:

- **`enablePDB: false` when `instances == 1`.** The CNPG-auto PDB has
  `minAvailable: 1` against 1 pod, which fires `PodDisruptionBudgetAtLimit`
  permanently on this SNO topology. Fixed in commit `8255b33`.
- **`argocd.argoproj.io/sync-wave: "-1"`.** The Cluster must reconcile and
  publish its `<cluster>-app` Secret before any sync-wave-0 workload (Helm
  release, Deployment) tries to mount that Secret. Added retroactively in
  commit `51d614b`.
- **`monitoring.enablePodMonitor: true`.** UWM only scrapes PodMonitors that
  opt in; both existing CNPG clusters in this repo set this.
- **Storage class `freenas-nvmeof-ssd-csi`.** Default for the cluster (see
  CLAUDE.md storage table). Override only if the workload has specific
  latency/IOPS needs.

## Target path

The target: **$ARGUMENTS**

Expected formats:
- `applications/<name>` or `components/<name>` — full path
- `<name>` — resolve by checking both
- If `$ARGUMENTS` is empty, ask the user for the target

## Step 1: Validate the target

1. Verify the directory exists and contains `kustomization.yaml`.
2. Read the existing `kustomization.yaml` to detect the namespace and existing
   resources.
3. If a `Cluster.postgresql.cnpg.io` already exists in the directory, warn the
   user and ask whether to add another (rare) or abort.

## Step 2: Verify the CNPG operator is installed

```bash
oc get csv -A -o json | jq -r '.items[] | select(.spec.displayName=="CloudNativePG") | "\(.metadata.namespace)/\(.metadata.name)\t\(.status.phase)"'
```

If no Succeeded CSV exists, warn the user that the Cluster will not reconcile
until the operator is installed (see `components/cloudnative-pg/`). Ask
whether to proceed anyway.

The operator's OperatorGroup is `AllNamespaces` (commit `aef3482`), so no
per-namespace operator setup is needed.

## Step 3: Gather information

Ask in a **single** message if not supplied inline:

| Field | Description | Default |
|-------|-------------|---------|
| `cluster-name` | `metadata.name` for the Cluster (becomes `<cluster-name>-app` Secret) | `<app-name>-pg` |
| `database` | initdb database name | `<app-name>` |
| `owner` | initdb owner role | `<app-name>` |
| `instances` | replica count | `1` |
| `storage-size` | PVC size | `10Gi` |
| `storage-class` | StorageClass | `freenas-nvmeof-ssd-csi` |
| `cpu-request` | container cpu request | `100m` |
| `mem-request` | container memory request | `256Mi` |
| `enable-pod-monitor` | emit `monitoring.enablePodMonitor: true` | `yes` |
| `sync-wave` | ArgoCD sync-wave annotation | `-1` |
| `env-prefix` | optional prefix for the workload env-from-secret snippet, e.g. `GITEA__database__` (`none` to skip) | ask |

Also verify the storage class exists:
```bash
oc get sc <storage-class>
```
If missing, warn before proceeding.

## Step 4: Generate the Cluster manifest

File name: `<cluster-name>-cluster.yaml` (matches the repo's
`<metadata.name>-<kind>.yaml` convention).

```yaml
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: <cluster-name>
  namespace: <namespace>
  annotations:
    argocd.argoproj.io/sync-wave: "<sync-wave>"
spec:
  instances: <instances>
  # Single-instance Postgres on SNO has no HA value to preserve and CNPG's
  # auto-PDB fires PodDisruptionBudgetAtLimit. Disable it. Re-enable only
  # if you raise instances to >= 2.
  enablePDB: false
  imagePullPolicy: IfNotPresent
  bootstrap:
    initdb:
      database: <database>
      owner: <owner>
  storage:
    size: <storage-size>
    storageClass: <storage-class>
  monitoring:
    enablePodMonitor: <enable-pod-monitor>
  resources:
    requests:
      cpu: <cpu-request>
      memory: <mem-request>
```

### Conditional rules (the skill must enforce)

1. **`enablePDB`**: emit `enablePDB: false` **iff `instances == 1`**, with the
   inline comment shown above. If `instances >= 2`, omit `enablePDB` entirely
   so CNPG's default PDB protects the primary.
2. **`monitoring` block**: omit it entirely if `enable-pod-monitor` is `no`.
3. **`enable-pod-monitor: true`** in YAML — emit unquoted `true`, not the
   string `"true"`.

### What NOT to add

- **No SCC RoleBinding for the CNPG pod.** The CSV handles its own SCC. The
  `nonroot-v2` Role/RoleBinding pattern in `applications/gitea/` and
  `applications/forgejo/` is for the *application's* ServiceAccount (e.g.
  `gitea`, `gitea-valkey-primary`), not for the Postgres pod.
- **No backup config.** This repo doesn't run Barman or another CNPG backup
  target today. Out of scope until a backup destination is configured.
- **No admin-user ExternalSecret.** If the workload also needs an
  application-admin Secret (gitea/forgejo pattern), tell the user to chain
  into `add-externalsecret` rather than reimplementing here.

## Step 5: Update kustomization.yaml

Use **Edit**, not Write, on the existing `kustomization.yaml`. Append
`<cluster-name>-cluster.yaml` to the `resources:` list. Place it before any
ExternalSecret entries (the Cluster is wave -1; ExternalSecrets are typically
0 or higher).

## Step 6: Validate

```bash
kustomize build <target-path>/
make lint
```

If either fails, diagnose and fix before reporting completion. Common issues:
- Wrong namespace in the manifest (must match the kustomization's `namespace:`)
- Missing newline at EOF (yamllint catches this)

## Step 7: Print the workload wiring snippet

CNPG publishes credentials in a Secret named `<cluster-name>-app` with keys:

| Key | Contents |
|-----|----------|
| `host` | service DNS name |
| `port` | `5432` |
| `dbname` | from `bootstrap.initdb.database` |
| `user` | (note: `user`, not `username`) |
| `username` | same as `user` (alias) |
| `password` | generated |
| `uri` | full `postgresql://...` URI |
| `jdbc-uri` | full `jdbc:postgresql://...` URI |

If the user provided an `env-prefix`, print this snippet for them to paste
into the workload's Helm values / Deployment / etc.:

```yaml
additionalConfigFromEnvs:    # name varies by chart; see your chart's values
  - name: <PREFIX>HOST
    valueFrom:
      secretKeyRef:
        name: <cluster-name>-app
        key: host
  - name: <PREFIX>NAME
    valueFrom:
      secretKeyRef:
        name: <cluster-name>-app
        key: dbname
  - name: <PREFIX>USER
    valueFrom:
      secretKeyRef:
        name: <cluster-name>-app
        key: username
  - name: <PREFIX>PASSWD
    valueFrom:
      secretKeyRef:
        name: <cluster-name>-app
        key: password
```

Do **not** auto-inject into the workload's Helm `valuesInline` — every chart
names the env block differently (`extraEnv`, `extraEnvFrom`,
`additionalConfigFromEnvs`, `env`, etc.) and the user is the right person to
pick the right key.

If `env-prefix == none`, skip this step and just tell the user the Secret
name and available keys.

## Completion report

Report:
1. **Operator check**: CSV phase / namespace
2. **Storage class check**: exists/missing
3. **File created**: full path
4. **kustomization.yaml update**: show the diff (one added line)
5. **Validation results**: `kustomize build` + `make lint` outcome
6. **Workload wiring**: the env-from-secret snippet (or just the Secret name
   if `env-prefix == none`)
7. **Next steps**: suggest `add-externalsecret` if the app needs an admin
   user secret, and remind the user to bump `instances` + remove `enablePDB:
   false` if they later want HA
